"""FastAPI façade over the existing ApexCoach engines/repositories (F16.1, docs/adr/0023).

This app does not duplicate or reimplement any decision/business logic. It is a
thin HTTP layer that calls the same `MetricsRepository` / `PlanRepository` /
engine functions the CLI already uses, against the same SQLite database.

Run from the repo root so `apex_coach` resolves on the Python path (mirrors
`pythonpath = ["."]` in pyproject.toml's pytest config):

    uvicorn web.backend.main:app --reload --port 8000

Config is loaded the exact same way the CLI loads it — see
`apex_coach/config/settings.py` and `apex_coach/cli/main.py`
(`create_engine(settings.database_url.removeprefix("sqlite:///"))`). Endpoint
handlers added by later tickets should follow that same pattern.
"""

import json
from datetime import date, datetime, timezone, timedelta
from types import SimpleNamespace

import click
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from apex_coach.adapters.errors import AdapterError
from apex_coach.adapters.ollama_adapter import RealOllamaAdapter
from apex_coach.adapters.whoop_adapter import RealWhoopAdapter
from apex_coach.cli.main import (
    DEFAULT_ACTIVITY_SYNC_PROVIDER,
    PERIODISATION_PHASES,
    SESSION_TYPES,
    _push_week,
    _resolve_todays_session,
    persist_decision_with_explanation,
    run_decision_pipeline,
)
from apex_coach.config.settings import get_settings
from apex_coach.db.engine import create_engine
from apex_coach.db.plan_repository import PlanRepository
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.token_repository import TokenRepository
from apex_coach.services.health_check import (
    FIXED_QUESTIONS,
    evaluate_health_check,
    get_adaptive_questions,
    persist_health_check,
)

# Loaded at import time so a missing APEX_ENCRYPTION_KEY (or other required
# env var) fails fast on startup, exactly like the CLI does — not used yet,
# but confirms the config-loading pattern is wired up correctly for later
# tickets to build on.
settings = get_settings()
engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
plan_repo = PlanRepository(engine)
metrics_repo = MetricsRepository(engine)

app = FastAPI(title="ApexCoach Web API")

# Local dev only (SDD roadmap: v2.0 is the real multi-user/Azure milestone).
# Allows the Vite dev server's default origin to call this API directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# -- F17.1: morning context (WHOOP fetch + session resolution + question --
# -- catalog) --------------------------------------------------------------
#
# Reuses apex_coach.cli.main's own `_resolve_todays_session()` rather than
# reimplementing the plan-lookup/fallback logic a second time (docs/adr/0023
# — no duplicated business logic). Importing a module-private helper across
# this boundary is a deliberate, narrow exception: it's a small, already-
# tested orchestration function with no CLI-specific behavior baked in, and
# duplicating it would be worse than the cross-module import.


def _whoop_biometrics_dict(payload) -> dict:
    return {
        "whoop_recovery_pct": payload.whoop_recovery_pct,
        "whoop_hrv_ms": payload.whoop_hrv_ms,
        "whoop_rhr_bpm": payload.whoop_rhr_bpm,
        "whoop_strain": payload.whoop_strain,
        "whoop_sleep_hours": payload.whoop_sleep_hours,
    }


def _question_catalog(session_type: str) -> dict:
    return {
        "fixed": [{"key": key, "text": text} for key, text in FIXED_QUESTIONS],
        "adaptive": [
            {"key": q.key, "text": q.text} for q in get_adaptive_questions(session_type)
        ],
    }


def _existing_decision_response(decision_row: dict | None) -> dict | None:
    """#132: builds an `existing_decision` payload shaped exactly like
    `POST /api/morning/decision`'s response from today's `decisions` row,
    or None if there's nothing rehydratable yet -- either no decision for
    the date, or only the bare crash-safe row (ADR-0001, inserted before
    Ollama ran) with no `llm_explanation`/`decision_context_json`. A
    degraded explanation (banner/WARN, no `llm_explanation`) is never
    persisted by `persist_decision_with_explanation()`, so a row with
    both fields populated always means `banner`/`severity` were None at
    generation time too."""
    if (
        decision_row is None
        or decision_row["llm_explanation"] is None
        or decision_row["decision_context_json"] is None
    ):
        return None
    rationale = json.loads(decision_row["rationale_json"]) if decision_row["rationale_json"] else {}
    return {
        "recommendation": decision_row["recommendation"],
        "rationale": rationale.get("rationale"),
        "check_recovery_week_trigger": rationale.get("check_recovery_week_trigger", False),
        "override_triggered": rationale.get("override_triggered", False),
        "override_reasons": rationale.get("override_reasons", []),
        "explanation": decision_row["llm_explanation"],
        "banner": None,
        "severity": None,
        "decision_context": json.loads(decision_row["decision_context_json"]),
    }


@app.get("/api/morning/context")
def morning_context(
    date_param: str | None = Query(default=None, alias="date"),
    session_type: str | None = Query(
        default=None, description="Fallback session type, used only if no plan covers `date`."
    ),
) -> dict:
    """Fetch+persist real WHOOP data, resolve today's scheduled session
    (plan-based, falling back to `session_type` if given), and return the
    biometrics plus the health-check question catalog for that session.

    If no plan covers `date` and no `session_type` fallback was given,
    responds 409 with `error: "no_plan_for_date"` and the already-fetched
    biometrics in the detail body, so the frontend can show a session-type
    picker alongside the WHOOP data rather than a bare error.
    """
    resolved_date = date_param or datetime.now(timezone.utc).date().isoformat()
    try:
        date.fromisoformat(resolved_date)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid date: {resolved_date!r}")

    if session_type is not None and session_type not in SESSION_TYPES:
        raise HTTPException(status_code=400, detail=f"unknown session_type: {session_type!r}")

    if not settings.whoop_client_id or not settings.whoop_client_secret:
        raise HTTPException(
            status_code=400, detail="WHOOP_CLIENT_ID / WHOOP_CLIENT_SECRET not set in .env."
        )

    token_repo = TokenRepository(engine, settings.apex_encryption_key)
    whoop_adapter = RealWhoopAdapter(
        token_repo, settings.whoop_client_id, settings.whoop_client_secret
    )
    try:
        whoop_payload = whoop_adapter.get_daily_payload(resolved_date)
    except AdapterError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    metrics_repo.upsert_daily_metrics(resolved_date, **_whoop_biometrics_dict(whoop_payload))
    biometrics = _whoop_biometrics_dict(whoop_payload)

    try:
        resolved_session_type, *_rest = _resolve_todays_session(
            plan_repo, resolved_date, session_type
        )
    except click.ClickException:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "no_plan_for_date",
                "message": (
                    "No weekly plan covers this date, and no fallback session_type "
                    "was given — pick one to continue."
                ),
                "biometrics": biometrics,
                "available_session_types": SESSION_TYPES,
            },
        )

    response = {
        "date": resolved_date,
        "session_type": resolved_session_type,
        "biometrics": biometrics,
        "questions": _question_catalog(resolved_session_type),
    }

    # #132: widen this response with today's already-decided outcome, if
    # one exists, so the frontend can rehydrate straight to it instead of
    # restarting the health check (server remains the source of truth,
    # refetched per date -- ADR-0023, no new client-side store).
    existing_decision = _existing_decision_response(plan_repo.get_decision(resolved_date))
    if existing_decision is not None:
        response["existing_decision"] = existing_decision

    return response


# -- F17.2: morning decision (health check -> classify -> decide -> --------
# -- persist -> Ollama explain) ---------------------------------------------
#
# Reuses apex_coach.cli.main.run_decision_pipeline()/
# persist_decision_with_explanation() — extracted from the CLI's own
# `morning` command in this same ticket specifically so the API Contract
# §4.3 Decision Context shape has exactly one implementation, not two that
# could drift (docs/adr/0023).


class MorningDecisionRequest(BaseModel):
    date: str
    session_type: str
    fixed_answers: dict[str, int]
    adaptive_answers: dict[str, int]


@app.post("/api/morning/decision")
def morning_decision(request: MorningDecisionRequest) -> dict:
    """Runs the health check, classification, and daily decision engine
    against WHOOP data already fetched by a prior GET /api/morning/context
    call for the same date, persists the Decision Output (bare row first,
    then a fuller row with the explanation once Ollama succeeds — same
    crash-safe ordering as the CLI, ADR-0001), and returns the
    recommendation/rationale/explanation plus the Decision Context (the
    frontend needs it verbatim for follow-up calls, #85)."""
    if request.session_type not in SESSION_TYPES:
        raise HTTPException(status_code=400, detail=f"unknown session_type: {request.session_type!r}")

    day_row = metrics_repo.get_daily_metrics(request.date)
    if (
        day_row is None
        or day_row["whoop_recovery_pct"] is None
        or day_row["whoop_hrv_ms"] is None
    ):
        raise HTTPException(
            status_code=400,
            detail="no WHOOP data persisted for this date — call GET /api/morning/context first",
        )

    # Re-resolve rather than trust the client's session_type blindly — this
    # is the same lookup GET /api/morning/context already did, idempotent,
    # and confirms the session_type still matches the current plan/fallback
    # (e.g. the athlete could have replanned the week between the two calls).
    try:
        resolved_session_type, week_plan, week_sessions, weekday_name, _week_start = (
            _resolve_todays_session(plan_repo, request.date, request.session_type)
        )
    except click.ClickException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        health_result = evaluate_health_check(
            resolved_session_type, request.fixed_answers, request.adaptive_answers
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    persist_health_check(metrics_repo, request.date, health_result)

    # WHOOP was already fetched (and persisted) by GET /api/morning/context
    # in an earlier request — run_decision_pipeline() only needs the 4
    # biometric attributes, so a SimpleNamespace built from the persisted
    # row satisfies its duck-typed `whoop_payload` interface without
    # re-fetching from WHOOP a second time for the same date.
    whoop_payload = SimpleNamespace(
        whoop_recovery_pct=day_row["whoop_recovery_pct"],
        whoop_hrv_ms=day_row["whoop_hrv_ms"],
        whoop_rhr_bpm=day_row["whoop_rhr_bpm"],
        whoop_strain=day_row["whoop_strain"],
    )

    try:
        decision_result, decision_context = run_decision_pipeline(
            plan_repo,
            metrics_repo,
            request.date,
            resolved_session_type,
            whoop_payload,
            request.fixed_answers,
            request.adaptive_answers,
            health_result,
            week_plan,
            week_sessions,
            weekday_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    ollama_adapter = RealOllamaAdapter()
    explanation_result = ollama_adapter.explain(decision_context)

    if not explanation_result.degraded:
        persist_decision_with_explanation(
            plan_repo,
            request.date,
            resolved_session_type,
            decision_result,
            decision_context,
            explanation_result.explanation,
        )

    return {
        "recommendation": decision_result["recommendation"],
        "rationale": decision_result["rationale"],
        "check_recovery_week_trigger": decision_result["check_recovery_week_trigger"],
        "override_triggered": health_result["override_triggered"],
        "override_reasons": health_result["override_reasons"],
        "explanation": explanation_result.explanation,
        "banner": explanation_result.banner,
        "severity": explanation_result.severity,
        "decision_context": decision_context,
    }


# -- F17.3: morning follow-up (conversational chat loop, #85) --------------
#
# Stateless on the server, mirroring apex_coach.cli.main's own
# `_run_followup_loop()` — the client holds the running conversation
# (decision_context + latest explanation) and resubmits it each turn.


class MorningFollowupRequest(BaseModel):
    decision_context: dict
    prior_explanation: str
    question: str


@app.post("/api/morning/followup")
def morning_followup(request: MorningFollowupRequest) -> dict:
    """Calls RealOllamaAdapter.ask_followup() with the given
    decision_context/prior_explanation/question and returns the
    explanation result (or a degraded banner) — no persistence, the
    Decision Output itself was already persisted by
    POST /api/morning/decision."""
    ollama_adapter = RealOllamaAdapter()
    result = ollama_adapter.ask_followup(
        request.decision_context, request.prior_explanation, request.question
    )
    return {
        "explanation": result.explanation,
        "banner": result.banner,
        "severity": result.severity,
    }


@app.get("/api/execution-score-trend")
def execution_score_trend(
    start_date: str = Query(..., description="YYYY-MM-DD, inclusive"),
    end_date: str = Query(..., description="YYYY-MM-DD, inclusive"),
) -> dict:
    """F16.4: execution_score over time + overpush/underpush counts.

    Reads `activities` + `session_scores` via `MetricsRepository`, mirroring
    the combine pattern in `apex_coach.engines.monthly_engine.run_monthly_review`
    (for each activity in range, fetch its most recent session_scores row and
    keep the ones that have one).
    """
    activities = metrics_repo.get_activities_range(start_date, end_date)

    points = []
    overpush_count = 0
    underpush_count = 0
    for activity in activities:
        score = metrics_repo.get_session_score(activity["id"])
        if score is None:
            continue
        points.append(
            {
                "date": activity["date"],
                "activity_id": activity["id"],
                "activity_type": activity.get("activity_type"),
                "intended_session_type": activity.get("intended_session_type"),
                "execution_score": score.get("execution_score"),
                "overpush_flag": bool(score.get("overpush_flag")),
                "underpush_flag": bool(score.get("underpush_flag")),
            }
        )
        if score.get("overpush_flag"):
            overpush_count += 1
        if score.get("underpush_flag"):
            underpush_count += 1

    return {
        "start_date": start_date,
        "end_date": end_date,
        "points": points,
        "overpush_count": overpush_count,
        "underpush_count": underpush_count,
    }


# -- F19.4/F19.7: web calendar week view + push (#119, #123) ----------------
#
# GET reuses PlanRepository.get_weekly_plan() to read weekly_plans.
# generated_structure_json — the same JSON already produced+persisted by
# F19.2's `generate-week-structure` CLI command (apex_coach.cli.main
# generate_week_structure_command / engines.structure_generator.
# generate_week_structure()). This endpoint only *reads* the persisted
# structure; it never calls the generator itself (docs/adr/0023 — no
# duplicated business logic, mirrors `_print_week_structure`'s reading
# logic). Per-day `pushed` now reflects whether that day has an event id in
# weekly_plans.pushed_event_ids_json (F19.7, #123) -- true "pushed" vs.
# local-only "draft", not the hardcoded `False` F19.4 shipped as a
# placeholder.
#
# `activity_sync_provider` is included so the frontend can disable/hide the
# push button for STRAVA athletes without a second round trip — same
# resolution as `_build_plan_export_adapter`'s (a NULL column defaults to
# DEFAULT_ACTIVITY_SYNC_PROVIDER, apex_coach.cli.main).
#
# POST /api/plan/week/push reuses `_push_week()` (apex_coach.cli.main) —
# the exact push logic behind the `push-week` CLI command (F19.6, #121):
# same adapter dispatch (intervals.icu-only, docs/adr/0027), same
# create-vs-update-in-place event id tracking. Not a second implementation.


def _resolved_activity_sync_provider() -> str:
    profile = plan_repo.get_athlete_profile()
    return (profile or {}).get("activity_sync_provider") or DEFAULT_ACTIVITY_SYNC_PROVIDER


def _structured_days(generated_structure_json: str, pushed_event_ids_json: str | None = None) -> list[dict]:
    """Turns a weekly_plans.generated_structure_json blob into the per-day
    payload shape both /api/plan/week and /api/plan/month return. Pulled out
    on its own so the month endpoint (F19.5, #120) doesn't reimplement this
    read logic a second time (docs/adr/0023). `pushed` reflects whether that
    day has an event id in weekly_plans.pushed_event_ids_json (F19.7, #123)
    -- true "pushed" vs. local-only "draft"."""
    structured = json.loads(generated_structure_json)
    pushed_event_ids = json.loads(pushed_event_ids_json or "{}")
    return [
        {
            "day": entry["day"],
            "session_type": entry["session_type"],
            "structure": entry["structure"],
            "pushed": bool(pushed_event_ids.get(entry["day"])),
        }
        for entry in structured
    ]


@app.get("/api/plan/week")
def plan_week(
    week_start: str = Query(
        ..., description="ISO 8601 date (YYYY-MM-DD) for the Monday this week starts on."
    ),
) -> dict:
    try:
        date.fromisoformat(week_start)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid date: {week_start!r}")

    week = plan_repo.get_weekly_plan(week_start)
    if week is None:
        raise HTTPException(
            status_code=404,
            detail=f"no weekly plan stored for week_start_date {week_start!r}",
        )

    activity_sync_provider = _resolved_activity_sync_provider()

    if not week.get("generated_structure_json"):
        return {
            "week_start_date": week_start,
            "generated": False,
            "days": [],
            "activity_sync_provider": activity_sync_provider,
        }

    return {
        "week_start_date": week_start,
        "generated": True,
        "days": _structured_days(week["generated_structure_json"], week.get("pushed_event_ids_json")),
        "activity_sync_provider": activity_sync_provider,
    }


# -- F19.5: web calendar month view (read-only preview, #120) ---------------
#
# Stitches together the weekly_plans rows for every week that overlaps the
# selected calendar month, one entry per week in the same shape
# GET /api/plan/week already returns (via the shared `_structured_days()`
# helper above) — so the frontend's month view can reuse F19.4's
# per-day/per-session rendering verbatim instead of a parallel
# implementation (#120's acceptance criteria). Unlike /api/plan/week, a week
# with no weekly_plans row at all is *not* a 404 here — a month is expected
# to have some weeks unplanned (e.g. the tail end of a month bleeding into
# next month's not-yet-generated week), so it's reported the same way as "row
# exists but ungenerated": {generated: false, days: []}.


def _week_view_payload(week_start: str) -> dict:
    week = plan_repo.get_weekly_plan(week_start)
    if week is None or not week.get("generated_structure_json"):
        return {"week_start_date": week_start, "generated": False, "days": []}
    return {
        "week_start_date": week_start,
        "generated": True,
        "days": _structured_days(week["generated_structure_json"], week.get("pushed_event_ids_json")),
    }


def _weeks_overlapping_month(month_first_day: date) -> list[str]:
    """ISO Monday dates (oldest first) for every week whose Mon-Sun span
    overlaps the calendar month starting on `month_first_day`."""
    if month_first_day.month == 12:
        next_month_first_day = date(month_first_day.year + 1, 1, 1)
    else:
        next_month_first_day = date(month_first_day.year, month_first_day.month + 1, 1)
    month_last_day = next_month_first_day - timedelta(days=1)

    first_week_start = _monday_on_or_before(month_first_day)
    last_week_start = _monday_on_or_before(month_last_day)

    week_starts = []
    current = first_week_start
    while current <= last_week_start:
        week_starts.append(current.isoformat())
        current += timedelta(weeks=1)
    return week_starts


@app.get("/api/plan/month")
def plan_month(
    month: str = Query(
        ..., description="ISO 8601 year-month (YYYY-MM) for the calendar month to view."
    ),
) -> dict:
    try:
        month_first_day = date.fromisoformat(f"{month}-01")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid month: {month!r}")

    weeks = [_week_view_payload(week_start) for week_start in _weeks_overlapping_month(month_first_day)]
    return {"month": month, "weeks": weeks}


@app.post("/api/plan/week/push")
def push_week_endpoint(
    week_start: str = Query(
        ..., description="ISO 8601 date (YYYY-MM-DD) for the Monday this week starts on."
    ),
) -> dict:
    """Push a week's generated structured plan to intervals.icu as calendar
    events, via `_push_week()` (apex_coach.cli.main, F19.6) — always against
    the real intervals.icu API (`real=True`): unlike the CLI's `push-week
    --real` flag, which defaults to a mock adapter for local demoing, a web
    UI button click has no non-real mode to fall back to.

    Maps `_push_week()`'s click.ClickException failures to HTTP errors: "no
    weekly plan stored" -> 404 (mirrors GET's own 404 for the same case);
    everything else (no generated structure yet, non-intervals.icu
    provider, no stored API key, adapter failure) -> 400.
    """
    try:
        date.fromisoformat(week_start)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid date: {week_start!r}")

    try:
        structured_sessions, updated_event_ids = _push_week(
            plan_repo, engine, settings, week_start, real=True
        )
    except click.ClickException as e:
        message = str(e)
        status_code = 404 if message.startswith("no weekly plan stored") else 400
        raise HTTPException(status_code=status_code, detail=message) from e

    return {
        "week_start_date": week_start,
        "pushed_days": [
            {"day": session["day"], "event_id": updated_event_ids[session["day"]]}
            for session in structured_sessions
        ],
    }


# -- F19.8: web UI for the monthly target (phase/load-target/race-date) ----
#
# The monthly target (periodisation_phase, load_target_total, race_date) was
# previously CLI-only (`set-monthly-target`, F11.8/#48). These endpoints are
# a thin HTTP wrapper around the exact same read/write path: GET reuses
# `PlanRepository.get_monthly_target()` (same as `plan_month`/`load_monthly`
# above), and POST reuses `PlanRepository.upsert_monthly_target()` — the
# identical insert-vs-update-by-existence branching `set-monthly-target`
# uses (moved onto PlanRepository itself in F20.3 so F20.3's macro-plan
# accept step can share it too, without an engines-module importing across
# the cli/web layering boundary) — so there is exactly one implementation
# of that branch (docs/adr/0023).


@app.get("/api/plan/month/target")
def get_monthly_target(
    month_start: str = Query(
        ..., description="ISO 8601 date (YYYY-MM-DD) for the first day of the month."
    ),
) -> dict:
    try:
        date.fromisoformat(month_start)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid date: {month_start!r}")

    target = plan_repo.get_monthly_target(month_start)
    if target is None:
        return {
            "month_start_date": month_start,
            "exists": False,
            "periodisation_phase": None,
            "load_target_total": None,
            "race_date": None,
        }
    return {
        "month_start_date": month_start,
        "exists": True,
        "periodisation_phase": target["periodisation_phase"],
        "load_target_total": target["load_target_total"],
        "race_date": target["race_date"],
    }


class MonthlyTargetRequest(BaseModel):
    periodisation_phase: str
    load_target_total: float
    race_date: str | None = None


@app.post("/api/plan/month/target")
def set_monthly_target_endpoint(
    request: MonthlyTargetRequest,
    month_start: str = Query(
        ..., description="ISO 8601 date (YYYY-MM-DD) for the first day of the month."
    ),
) -> dict:
    """Create (first write for `month_start`) or update (subsequent writes)
    the monthly target, via `PlanRepository.upsert_monthly_target()` — no
    parallel persistence path to `set-monthly-target`."""
    try:
        date.fromisoformat(month_start)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid date: {month_start!r}")

    if request.periodisation_phase not in PERIODISATION_PHASES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown periodisation_phase: {request.periodisation_phase!r}",
        )

    if request.race_date is not None:
        try:
            date.fromisoformat(request.race_date)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid race_date: {request.race_date!r}")

    created = plan_repo.upsert_monthly_target(
        month_start,
        request.periodisation_phase,
        request.load_target_total,
        request.race_date,
    )
    target = plan_repo.get_monthly_target(month_start)
    return {
        "month_start_date": month_start,
        "created": created,
        "periodisation_phase": target["periodisation_phase"],
        "load_target_total": target["load_target_total"],
        "race_date": target["race_date"],
    }


# -- F16.3: load actual vs. target (weekly + monthly) -----------------------
#
# PlanRepository has no "get a range of weeks/months" method, only a
# single-row lookup by exact period-start date (get_weekly_plan /
# get_monthly_target). These endpoints accept an explicit, comma-separated
# list of period-start dates via a query param — the caller picks exactly
# which weeks/months it wants — and fall back to computing N trailing
# periods ending at the current week/month when no explicit list is given,
# which is what the chart page uses by default. Missing rows (no plan/target
# recorded for that period yet) are returned with null actual/target rather
# than omitted, so the chart can still render a gap for that period.


def _monday_on_or_before(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _trailing_week_starts(count: int) -> list[str]:
    """ISO date strings for `count` Mondays, oldest first, ending at the
    Monday of the current week."""
    current_monday = _monday_on_or_before(date.today())
    return [
        (current_monday - timedelta(weeks=offset)).isoformat()
        for offset in range(count - 1, -1, -1)
    ]


def _trailing_month_starts(count: int) -> list[str]:
    """ISO date strings for the 1st of `count` months, oldest first, ending
    at the 1st of the current month."""
    today = date.today()
    starts: list[str] = []
    for offset in range(count - 1, -1, -1):
        month_index = today.month - 1 - offset  # 0-based, may be negative
        year = today.year + month_index // 12
        month = month_index % 12 + 1
        starts.append(date(year, month, 1).isoformat())
    return starts


@app.get("/api/load/weekly")
def load_weekly(
    week_start_dates: str | None = None, weeks: int = 8
) -> dict[str, list[dict]]:
    """Load actual vs. target per week.

    Query params:
    - `week_start_dates`: optional comma-separated list of ISO Monday dates,
      e.g. `2026-06-01,2026-06-08`. When given, exactly these weeks are
      returned (in the order given).
    - `weeks`: when `week_start_dates` is omitted, the number of trailing
      weeks (ending at the current week) to return. Default 8.
    """
    dates = (
        [d.strip() for d in week_start_dates.split(",") if d.strip()]
        if week_start_dates
        else _trailing_week_starts(weeks)
    )
    result = []
    for week_start_date in dates:
        row = plan_repo.get_weekly_plan(week_start_date)
        result.append(
            {
                "week_start_date": week_start_date,
                "load_actual": row["load_actual"] if row else None,
                "load_target": row["load_target"] if row else None,
            }
        )
    return {"weeks": result}


@app.get("/api/load/monthly")
def load_monthly(
    month_start_dates: str | None = None, months: int = 6
) -> dict[str, list[dict]]:
    """Load actual vs. target per month.

    Query params:
    - `month_start_dates`: optional comma-separated list of ISO
      first-of-month dates, e.g. `2026-05-01,2026-06-01`. When given,
      exactly these months are returned (in the order given).
    - `months`: when `month_start_dates` is omitted, the number of trailing
      months (ending at the current month) to return. Default 6.
    """
    dates = (
        [d.strip() for d in month_start_dates.split(",") if d.strip()]
        if month_start_dates
        else _trailing_month_starts(months)
    )
    result = []
    for month_start_date in dates:
        row = plan_repo.get_monthly_target(month_start_date)
        result.append(
            {
                "month_start_date": month_start_date,
                "load_actual_total": row["load_actual_total"] if row else None,
                "load_target_total": row["load_target_total"] if row else None,
            }
        )
    return {"months": result}


DEFAULT_TREND_WINDOW_DAYS = 30


@app.get("/api/trends/hrv")
def hrv_trend(
    start: str | None = Query(
        default=None, description="Inclusive start date, YYYY-MM-DD."
    ),
    end: str | None = Query(
        default=None, description="Inclusive end date, YYYY-MM-DD."
    ),
) -> list[dict]:
    """Real `whoop_hrv_ms` readings over an inclusive date range, via
    `MetricsRepository.get_daily_metrics_range()`.

    `start`/`end` are optional ISO date strings (YYYY-MM-DD). If omitted,
    defaults to the trailing 30 days (today minus 29 days through today).
    Returns a list of `{"date": str, "whoop_hrv_ms": float | None}`, ordered
    by date, one entry per `daily_metrics` row in range (rows with no HRV
    reading yet still appear, with `whoop_hrv_ms: null`, so the frontend can
    tell "no row that day" apart from "empty range" if it ever needs to).
    """
    if end is None:
        end = date.today().isoformat()
    if start is None:
        start = (date.today() - timedelta(days=DEFAULT_TREND_WINDOW_DAYS - 1)).isoformat()

    rows = metrics_repo.get_daily_metrics_range(start, end)
    return [{"date": row["date"], "whoop_hrv_ms": row["whoop_hrv_ms"]} for row in rows]
