"""CLI entry point — command group. See docs/adr/0008."""

import json
from datetime import date as _date
from datetime import datetime, timedelta, timezone

import click

from apex_coach.adapters.errors import AdapterError
from apex_coach.adapters.ollama_adapter import MockOllamaAdapter, RealOllamaAdapter
from apex_coach.adapters.intervals_icu_adapter import (
    MockIntervalsIcuAdapter,
    RealIntervalsIcuAdapter,
)
from apex_coach.adapters.plan_export_adapter import MockPlanExportAdapter
from apex_coach.adapters.strava_adapter import (
    MockStravaAdapter,
    RealStravaAdapter,
    run_authorization_flow as run_strava_authorization_flow,
)
from apex_coach.adapters.whoop_adapter import (
    MockWhoopAdapter,
    RealWhoopAdapter,
    run_authorization_flow as run_whoop_authorization_flow,
)
from apex_coach.config.settings import get_settings
from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.plan_repository import PlanRepository
from apex_coach.db.schema import metadata
from apex_coach.db.token_repository import TokenRepository
from apex_coach.engines.daily_engine import KEY_SESSION_TYPES, make_decision
from apex_coach.engines.macro_plan_engine import (
    accept_macro_plan,
    preview_macro_plan,
    regenerate_macro_plan,
)
from apex_coach.engines.monthly_engine import (
    calculate_weekly_target,
    load_au_for_activity,
    run_monthly_review,
)
from apex_coach.engines.structure_generator import generate_week_structure
from apex_coach.engines.weekly_engine import run_weekly_adaptation
from apex_coach.orchestrator.orchestrator import (
    HRVDeltaBand,
    RecoveryBand,
    SorenessBand,
    classify_daily_inputs,
)
from apex_coach.services.hrv_trend import resolve_hrv_30d_avg_for_classification
from apex_coach.services.load_calculator import calculate_load_au
from apex_coach.services.session_scorer import persist_session_score, score_session
from apex_coach.services.health_check import (
    FIXED_QUESTIONS,
    evaluate_health_check,
    get_adaptive_questions,
    persist_health_check,
)
from apex_coach.services.zone_calculator import calculate_zones

ZONE_LABELS = {
    "zone1": "Zone 1 (Recovery)",
    "zone2": "Zone 2 (Aerobic base)",
    "zone3": "Zone 3 (Tempo)",
    "zone4": "Zone 4 (Threshold)",
    "zone5": "Zone 5 (VO2max)",
}

PERIODISATION_PHASES = ["BASE", "BUILD", "PEAK", "TAPER", "RECOVERY"]

# PRD #138 (F20.1) — race_goals.goal_distance's enum, the set of distances
# RACE_DISTANCE_PHASE_TEMPLATES (F20.2) will template a macro plan for.
RACE_DISTANCE_CHOICES = ["5K", "10K", "HALF_MARATHON", "MARATHON"]

# docs/adr/0024 — the Banister TRIMP formula's exponential weighting
# constant is only calibrated for these two categories in the source
# research.
ATHLETE_SEX_CHOICES = ["MALE", "FEMALE"]

# docs/adr/0025 (PRD #89) — which adapter sync-session dispatches to.
# A NULL athlete_profile.activity_sync_provider is treated as this default.
# intervals.icu is the default (F18.6/#95) — Strava is still fully
# supported, just no longer the un-configured fallback (Strava's paywalled
# API access was the reason for this PRD in the first place).
ACTIVITY_SYNC_PROVIDER_CHOICES = ["STRAVA", "INTERVALS_ICU"]
DEFAULT_ACTIVITY_SYNC_PROVIDER = "INTERVALS_ICU"

# Canonical session-type vocabulary — must match the `today` command's
# --session-type choices and what the decision/weekly engines expect.
SESSION_TYPES = [
    "HIIT",
    "Threshold",
    "Zone2_Long",
    "Zone2_Short",
    "Strength",
    "Recovery",
    "Rest",
]

# score_session's vocabulary minus Rest — Rest has no structured activity to
# sync (session_scorer.py §2.4/§6.1).
SCORABLE_SESSION_TYPES = [t for t in SESSION_TYPES if t != "Rest"]

WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

# Generic, session-type-level description for the Decision Context's
# todays_plan.session_description (API Contract §4.3) — there's no per-day
# structured workout description stored anywhere yet, so this is the
# coarsest-grain text that's still accurate.
SESSION_DESCRIPTIONS = {
    "HIIT": "High-intensity intervals at Zone 5 HR.",
    "Threshold": "Sustained tempo effort at Zone 4 HR.",
    "Zone2_Long": "Long aerobic base session at Zone 2 HR.",
    "Zone2_Short": "Short aerobic base session at Zone 2 HR.",
    "Strength": "Strength training session (RPE-based, no HR target).",
    "Recovery": "Active recovery — light movement at Zone 1 HR.",
    "Rest": "Full rest day — no structured training.",
}


@click.group()
def cli():
    pass


@cli.command()
@click.option("--max-hr", type=int, required=True, help="Max HR (bpm).")
@click.option("--resting-hr", type=int, required=True, help="Resting HR (bpm).")
def zones(max_hr: int, resting_hr: int):
    """Print the 5 HR zone boundaries for the given Max HR and Resting HR."""
    zone_boundaries = calculate_zones(max_hr, resting_hr)
    for zone_name, (lower, upper) in zone_boundaries.items():
        click.echo(f"{ZONE_LABELS[zone_name]}: {lower}-{upper} bpm")


@cli.command(name="init-db")
def init_db():
    """Create the SQLite schema (all tables in db/schema.py) if it doesn't
    already exist. Run this once before connect-whoop or any other command
    that touches the database — nothing else creates the schema."""
    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    metadata.create_all(engine)
    click.echo(f"Database initialized at {settings.database_url}")


@cli.command(name="connect-whoop")
def connect_whoop():
    """One-time browser OAuth handshake (API Contract §2.1). Requires
    WHOOP_CLIENT_ID/WHOOP_CLIENT_SECRET in .env — run this before
    `whoop-smoke --real`."""
    settings = get_settings()
    if not settings.whoop_client_id or not settings.whoop_client_secret:
        raise click.ClickException(
            "WHOOP_CLIENT_ID / WHOOP_CLIENT_SECRET not set — register an app "
            "at developer.whoop.com and add them to .env first."
        )

    try:
        tokens = run_whoop_authorization_flow(
            settings.whoop_client_id, settings.whoop_client_secret, settings.whoop_redirect_uri
        )
    except AdapterError as e:
        raise click.ClickException(str(e)) from e

    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    token_repo = TokenRepository(engine, settings.apex_encryption_key)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=tokens["expires_in"])
    ).isoformat()
    token_repo.save_token(
        provider="WHOOP",
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_at=expires_at,
        scope=tokens.get("scope", ""),
    )
    click.echo("WHOOP connected. Token stored — run `whoop-smoke --real` to verify.")


@cli.command(name="connect-strava")
def connect_strava():
    """One-time browser OAuth handshake (API Contract §3.1). Requires
    STRAVA_CLIENT_ID/STRAVA_CLIENT_SECRET in .env — run this before
    `strava-smoke --real`."""
    settings = get_settings()
    if not settings.strava_client_id or not settings.strava_client_secret:
        raise click.ClickException(
            "STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET not set — register an app "
            "at strava.com/settings/api and add them to .env first."
        )

    try:
        tokens = run_strava_authorization_flow(
            settings.strava_client_id, settings.strava_client_secret, settings.strava_redirect_uri
        )
    except AdapterError as e:
        raise click.ClickException(str(e)) from e

    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    token_repo = TokenRepository(engine, settings.apex_encryption_key)
    expires_at = datetime.fromtimestamp(tokens["expires_at"], tz=timezone.utc).isoformat()
    token_repo.save_token(
        provider="STRAVA",
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_at=expires_at,
        scope=tokens.get("scope", ""),
    )
    click.echo("Strava connected. Token stored — run `strava-smoke --real` to verify.")


@cli.command(name="connect-intervals-icu")
@click.option(
    "--api-key",
    prompt=True,
    hide_input=True,
    help="Personal API key from intervals.icu Settings > API. Prompted "
    "interactively (hidden input) if omitted.",
)
def connect_intervals_icu(api_key: str):
    """Store an intervals.icu personal API key (docs/adr/0025 §1). No OAuth
    handshake — this is a static, long-lived credential, encrypted at rest
    via the same TokenRepository WHOOP/Strava tokens use."""
    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    token_repo = TokenRepository(engine, settings.apex_encryption_key)
    token_repo.save_token(
        provider="INTERVALS_ICU",
        access_token=api_key,
        refresh_token="",
        expires_at="",
        scope="",
    )
    click.echo(
        "intervals.icu connected. API key stored — run "
        "`set-athlete-profile --activity-sync-provider INTERVALS_ICU` to make it "
        "sync-session's active provider."
    )


@cli.command(name="whoop-smoke")
@click.option(
    "--date",
    default=None,
    help="ISO 8601 date to fetch (defaults to today, UTC).",
)
@click.option(
    "--real", is_flag=True, default=False, help="Use RealWhoopAdapter instead of the mock."
)
def whoop_smoke(date: str | None, real: bool):
    """Fetch today's WHOOP daily payload (recovery, cycle, sleep) and print it.
    Mock by default (no network calls); --real hits the live API."""
    if date is None:
        date = datetime.now(timezone.utc).date().isoformat()

    engine = None
    if real:
        settings = get_settings()
        if not settings.whoop_client_id or not settings.whoop_client_secret:
            raise click.ClickException("WHOOP_CLIENT_ID / WHOOP_CLIENT_SECRET not set in .env.")
        engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
        token_repo = TokenRepository(engine, settings.apex_encryption_key)
        adapter = RealWhoopAdapter(token_repo, settings.whoop_client_id, settings.whoop_client_secret)
    else:
        adapter = MockWhoopAdapter()

    try:
        payload = adapter.get_daily_payload(date)
    except AdapterError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"Recovery: {payload.whoop_recovery_pct}%")
    click.echo(f"HRV: {payload.whoop_hrv_ms} ms")
    click.echo(f"RHR: {payload.whoop_rhr_bpm} bpm")
    click.echo(f"Strain: {payload.whoop_strain}")

    if real:
        MetricsRepository(engine).upsert_daily_metrics(
            date,
            whoop_recovery_pct=payload.whoop_recovery_pct,
            whoop_hrv_ms=payload.whoop_hrv_ms,
            whoop_rhr_bpm=payload.whoop_rhr_bpm,
            whoop_strain=payload.whoop_strain,
            whoop_sleep_hours=payload.whoop_sleep_hours,
        )
        click.echo(f"Persisted to daily_metrics for {date}.")


@cli.command(name="strava-smoke")
@click.option(
    "--since-ts",
    type=int,
    default=0,
    help="Unix timestamp — fetch activities newer than this (defaults to 0, all).",
)
@click.option(
    "--real", is_flag=True, default=False, help="Use RealStravaAdapter instead of the mock."
)
def strava_smoke(since_ts: int, real: bool):
    """Fetch recent Strava activities and print them. Mock by default (no
    network calls); --real hits the live API."""
    if real:
        settings = get_settings()
        if not settings.strava_client_id or not settings.strava_client_secret:
            raise click.ClickException("STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET not set in .env.")
        engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
        token_repo = TokenRepository(engine, settings.apex_encryption_key)
        adapter = RealStravaAdapter(
            token_repo, settings.strava_client_id, settings.strava_client_secret
        )
    else:
        adapter = MockStravaAdapter()

    try:
        activities = adapter.get_new_activities(since_ts)
    except AdapterError as e:
        raise click.ClickException(str(e)) from e

    for activity in activities:
        click.echo(f"{activity.name} ({activity.type})")
        click.echo(f"  Distance: {activity.distance} m")
        click.echo(f"  Duration: {activity.elapsed_time} s")
        hr = activity.average_heartrate
        click.echo(f"  Avg HR: {hr} bpm" if hr is not None else "  Avg HR: n/a")
        pace = activity.pace_sec_per_km
        click.echo(f"  Pace: {pace:.1f} sec/km" if pace is not None else "  Pace: n/a")
        click.echo(f"  Elevation gain: {activity.total_elevation_gain} m")


@cli.command(name="morning-check")
@click.option(
    "--session-type",
    required=True,
    type=click.Choice(SESSION_TYPES),
    help="Today's planned session type — selects the adaptive question set.",
)
@click.option(
    "--date",
    default=None,
    help="ISO 8601 date this check applies to (defaults to today, UTC).",
)
def morning_check(session_type: str, date: str | None):
    """Interactive morning health check: ask the 3 fixed questions plus the
    session type's adaptive questions, score the answers, and persist them
    to daily_metrics (API Contract / docs/adr/0012)."""
    if date is None:
        date = datetime.now(timezone.utc).date().isoformat()

    fixed_answers = {}
    for key, text in FIXED_QUESTIONS:
        fixed_answers[key] = click.prompt(text, type=click.IntRange(1, 5))

    adaptive_answers = {}
    for question in get_adaptive_questions(session_type):
        adaptive_answers[question.key] = click.prompt(question.text, type=click.IntRange(1, 5))

    result = evaluate_health_check(session_type, fixed_answers, adaptive_answers)

    if result["override_triggered"]:
        click.echo("Override triggered:")
        for reason in result["override_reasons"]:
            click.echo(f"  - {reason}")

    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    repo = MetricsRepository(engine)
    persist_health_check(repo, date, result)

    if result["override_triggered"]:
        click.echo(f"Health check for {date} saved — override noted above.")
    else:
        click.echo(f"Health check for {date} saved.")


@cli.command()
@click.option(
    "--session-type",
    required=True,
    type=click.Choice(SESSION_TYPES),
)
@click.option(
    "--recovery-band", required=True, type=click.Choice([b.value for b in RecoveryBand])
)
@click.option(
    "--hrv-signal", required=True, type=click.Choice([b.value for b in HRVDeltaBand])
)
@click.option(
    "--soreness-band", required=True, type=click.Choice([b.value for b in SorenessBand])
)
@click.option(
    "--override", is_flag=True, default=False, help="Force the joint-pain safety override."
)
@click.option(
    "--tomorrow-session-type",
    default=None,
    help="Only used for Recovery/Rest — adds a CNS primer if tomorrow is a Key session.",
)
def today(
    session_type: str,
    recovery_band: str,
    hrv_signal: str,
    soreness_band: str,
    override: bool,
    tomorrow_session_type: str | None,
):
    """Run the Daily Decision Engine and print a Decision Output + rationale.

    Inputs are passed as flags — no live morning-run pipeline exists yet
    (Orchestrator only classifies, health_check only scores); this is a
    smoke test of daily_engine end-to-end, matching the other *-smoke commands.
    """
    result = make_decision(
        session_type=session_type,
        recovery_band=RecoveryBand(recovery_band),
        hrv_signal=HRVDeltaBand(hrv_signal),
        soreness_band=SorenessBand(soreness_band),
        override_triggered=override,
        override_reasons=["--override flag set"] if override else None,
        tomorrow_session_type=tomorrow_session_type,
    )

    click.echo(f"Recommendation: {result['recommendation']}")
    click.echo(f"Rationale: {result['rationale'] or '(none)'}")
    if result["check_recovery_week_trigger"]:
        click.echo("[Flag: check_recovery_week_trigger]")


def _build_activity_sync_adapter(engine, settings, profile: dict | None, real: bool):
    """Dispatches to Strava or intervals.icu based on
    athlete_profile.activity_sync_provider (docs/adr/0025, PRD #89) — same
    selection logic for both mock and real modes, so `sync-session`
    (without --real) demos against whichever provider is configured."""
    provider = (profile or {}).get("activity_sync_provider") or DEFAULT_ACTIVITY_SYNC_PROVIDER

    if not real:
        return MockStravaAdapter() if provider == "STRAVA" else MockIntervalsIcuAdapter()

    token_repo = TokenRepository(engine, settings.apex_encryption_key)
    if provider == "STRAVA":
        if not settings.strava_client_id or not settings.strava_client_secret:
            raise click.ClickException("STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET not set in .env.")
        return RealStravaAdapter(
            token_repo, settings.strava_client_id, settings.strava_client_secret
        )

    token = token_repo.get_token("INTERVALS_ICU")
    if token is None:
        raise click.ClickException(
            "No intervals.icu API key stored — run `connect-intervals-icu` first."
        )
    return RealIntervalsIcuAdapter(token["access_token"])


def _build_plan_export_adapter(engine, settings, profile: dict | None, real: bool):
    """Plan export (calendar push) is intervals.icu-only — Strava has no
    write/calendar equivalent (PlanExportAdapterProtocol, docs/adr/0027).
    A Strava-configured athlete gets a clear error, not a crash."""
    provider = (profile or {}).get("activity_sync_provider") or DEFAULT_ACTIVITY_SYNC_PROVIDER
    if provider != "INTERVALS_ICU":
        raise click.ClickException(
            "Pushing a plan to a calendar is only supported for intervals.icu — "
            f"this athlete's activity_sync_provider is {provider!r}."
        )

    if not real:
        return MockPlanExportAdapter()

    token_repo = TokenRepository(engine, settings.apex_encryption_key)
    token = token_repo.get_token("INTERVALS_ICU")
    if token is None:
        raise click.ClickException(
            "No intervals.icu API key stored — run `connect-intervals-icu` first."
        )
    return RealIntervalsIcuAdapter(token["access_token"])


@cli.command(name="sync-session")
@click.option(
    "--session-type",
    required=True,
    type=click.Choice(SCORABLE_SESSION_TYPES),
    help="Which session this activity was meant to be — resolves the intended HR zone.",
)
@click.option(
    "--max-hr",
    type=int,
    default=None,
    help="Max HR (bpm), for zone resolution and TRIMP load. Defaults from the "
    "stored athlete profile (set-athlete-profile) if omitted.",
)
@click.option(
    "--resting-hr",
    type=int,
    default=None,
    help="Resting HR (bpm), for zone resolution. Defaults from the stored athlete "
    "profile if omitted. TRIMP load calculation prefers the day-of WHOOP resting "
    "HR over this flag regardless (docs/adr/0024).",
)
@click.option(
    "--since-ts",
    type=int,
    default=0,
    help=(
        "Unix timestamp — fetch Strava activities newer than this (defaults to 0, "
        "all). Simplest correct 'since last sync' marker: pass the timestamp of your "
        "last successful sync-session run yourself; this command does not track it "
        "for you."
    ),
)
@click.option(
    "--planned-load",
    type=float,
    default=None,
    help=(
        "Planned load (AU) this session targeted, for load_delta_score. No "
        "weekly-plan-derived planned load is available yet (F08 not wired up) — "
        "defaults to the just-computed actual_load_au (i.e. a 0 delta) if omitted."
    ),
)
@click.option(
    "--rpe",
    type=click.IntRange(1, 10),
    default=None,
    help="Athlete's RPE (1-10) for this session. Prompted interactively if omitted.",
)
@click.option(
    "--real",
    is_flag=True,
    default=False,
    help="Use the real adapter (Strava or intervals.icu, per athlete_profile."
    "activity_sync_provider) instead of the mock.",
)
def sync_session(
    session_type: str,
    max_hr: int | None,
    resting_hr: int | None,
    since_ts: int,
    planned_load: float | None,
    rpe: int | None,
    real: bool,
):
    """Close the loop after a real session: fetch new activities from the
    configured provider (Strava or intervals.icu, docs/adr/0025), let the
    athlete pick one, compute load_score, prompt for RPE, score execution
    against zone boundaries, and persist both the activity and the session
    score.

    Re-running against an activity that was already synced upserts the
    activity row (matched on strava_id) rather than erroring, and appends
    a fresh session_scores row (append-only, ADR-0006).
    """
    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    repo = MetricsRepository(engine)
    plan_repo = PlanRepository(engine)
    profile = plan_repo.get_athlete_profile()

    max_hr = max_hr if max_hr is not None else (profile.get("max_hr") if profile else None)
    resting_hr = (
        resting_hr
        if resting_hr is not None
        else (profile.get("baseline_resting_hr") if profile else None)
    )
    if max_hr is None or resting_hr is None:
        raise click.ClickException(
            "--max-hr/--resting-hr not provided and no athlete profile stored — "
            "pass the flags, or run `set-athlete-profile` first."
        )

    adapter = _build_activity_sync_adapter(engine, settings, profile, real)

    try:
        candidates = adapter.get_new_activities(since_ts)
    except AdapterError as e:
        raise click.ClickException(str(e)) from e

    if not candidates:
        click.echo("No new activities to sync.")
        return

    if len(candidates) == 1:
        activity = candidates[0]
    else:
        click.echo("Multiple new activities found:")
        for idx, candidate in enumerate(candidates):
            click.echo(
                f"  [{idx}] {candidate.name} ({candidate.type}) "
                f"— {candidate.start_date.isoformat()}, {candidate.elapsed_time}s"
            )
        index = click.prompt(
            "Select the activity to score", type=click.IntRange(0, len(candidates) - 1)
        )
        activity = candidates[index]

    try:
        stream = adapter.get_activity_stream(activity.id)
    except AdapterError as e:
        raise click.ClickException(str(e)) from e
    if stream is None:
        raise click.ClickException(
            f"No HR stream available for activity {activity.id} — cannot score execution."
        )

    if rpe is None:
        rpe = click.prompt("RPE for this session (1-10)", type=click.IntRange(1, 10))

    date_str = activity.start_date.date().isoformat()
    day_metrics = repo.get_daily_metrics(date_str)

    duration_minutes = activity.elapsed_time / 60
    try:
        if activity.type == "WeightTraining":
            load_score = calculate_load_au(activity.type, duration_minutes, rpe=rpe)
        else:
            # TRIMP prefers the day-of WHOOP resting HR over the athlete
            # profile / --resting-hr flag (docs/adr/0024) — resting HR
            # genuinely fluctuates day to day, so the actual reading for
            # this session's date is the most accurate signal available.
            trimp_resting_hr = (
                (day_metrics.get("whoop_rhr_bpm") if day_metrics else None) or resting_hr
            )
            load_score = calculate_load_au(
                activity.type,
                duration_minutes,
                avg_hr_bpm=activity.average_heartrate,
                resting_hr=trimp_resting_hr,
                max_hr=max_hr,
                sex=profile.get("sex") if profile else None,
            )
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    planned_load_au = planned_load if planned_load is not None else load_score
    zone_boundaries = calculate_zones(max_hr, resting_hr)

    try:
        result = score_session(
            session_type=session_type,
            hr_data=stream.heartrate.data,
            zone_boundaries=None if session_type == "Strength" else zone_boundaries,
            actual_rpe=rpe,
            actual_load_au=load_score,
            planned_load_au=planned_load_au,
        )
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    if day_metrics is None:
        repo.insert_daily_metrics(date=date_str)

    strava_id = str(activity.id)
    repo.save_activity(
        strava_id=strava_id,
        date=date_str,
        activity_type=activity.type,
        intended_session_type=session_type,
        duration_seconds=activity.elapsed_time,
        distance_metres=activity.distance,
        elevation_gain_m=activity.total_elevation_gain,
        avg_hr_bpm=(
            round(activity.average_heartrate) if activity.average_heartrate is not None else None
        ),
        max_hr_bpm=round(activity.max_heartrate) if activity.max_heartrate is not None else None,
        avg_pace_sec_per_km=activity.pace_sec_per_km,
        load_score=load_score,
        strava_raw_json=json.dumps(activity.model_dump(mode="json")),
    )
    repo.update_activity_rpe(strava_id, rpe)

    activity_row = repo.get_activity(strava_id)
    score_id = persist_session_score(repo, activity_row["id"], result)

    click.echo(f"Synced activity {activity.name} ({strava_id}) — load_score={load_score:.1f} AU")
    click.echo(
        f"Session score {score_id}: execution_score={result['execution_score']:.1f}"
        f" time_in_zone_pct={result['time_in_zone_pct']}"
        f" overpush={result['overpush_flag']} underpush={result['underpush_flag']}"
    )
@cli.command(name="plan-week")
@click.option(
    "--week-start",
    required=True,
    help="ISO 8601 date (YYYY-MM-DD) for the Monday this plan starts on.",
)
@click.option("--monday", type=click.Choice(SESSION_TYPES))
@click.option("--tuesday", type=click.Choice(SESSION_TYPES))
@click.option("--wednesday", type=click.Choice(SESSION_TYPES))
@click.option("--thursday", type=click.Choice(SESSION_TYPES))
@click.option("--friday", type=click.Choice(SESSION_TYPES))
@click.option("--saturday", type=click.Choice(SESSION_TYPES))
@click.option("--sunday", type=click.Choice(SESSION_TYPES))
@click.option(
    "--show",
    is_flag=True,
    default=False,
    help="Print the currently stored plan for --week-start instead of writing one.",
)
def plan_week(
    week_start: str,
    monday: str | None,
    tuesday: str | None,
    wednesday: str | None,
    thursday: str | None,
    friday: str | None,
    saturday: str | None,
    sunday: str | None,
    show: bool,
):
    """Write (or show) the upcoming week's planned sessions.

    Persists to weekly_plans.planned_sessions_json as a JSON list of
    {"day": <weekday name>, "session_type": <one of SESSION_TYPES>} dicts —
    the same shape apex_coach.engines.weekly_engine already reads/writes.

    Inserts a new weekly_plans row if --week-start hasn't been planned yet,
    or overwrites planned_sessions_json in place if it has.
    """
    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    plan_repo = PlanRepository(engine)

    if show:
        week = plan_repo.get_weekly_plan(week_start)
        if week is None:
            raise click.ClickException(
                f"no weekly plan stored for week_start_date {week_start!r}"
            )
        sessions = json.loads(week["planned_sessions_json"] or "[]")
        if not sessions:
            click.echo(f"No sessions planned for week starting {week_start}.")
            return
        click.echo(f"Plan for week starting {week_start}:")
        for entry in sessions:
            click.echo(f"  {entry['day']}: {entry['session_type']}")
        return

    day_values = {
        "Monday": monday,
        "Tuesday": tuesday,
        "Wednesday": wednesday,
        "Thursday": thursday,
        "Friday": friday,
        "Saturday": saturday,
        "Sunday": sunday,
    }
    missing = [day for day in WEEKDAYS if day_values[day] is None]
    if missing:
        raise click.ClickException(
            "missing --session-type for: " + ", ".join(d.lower() for d in missing)
        )

    planned_sessions = [
        {"day": day, "session_type": day_values[day]} for day in WEEKDAYS
    ]
    planned_sessions_json = json.dumps(planned_sessions)

    if plan_repo.get_weekly_plan(week_start) is None:
        plan_repo.insert_weekly_plan(
            week_start_date=week_start,
            planned_sessions_json=planned_sessions_json,
        )
    else:
        plan_repo.update_weekly_plan(
            week_start,
            planned_sessions_json=planned_sessions_json,
        )

    click.echo(f"Plan saved for week starting {week_start}:")
    for entry in planned_sessions:
        click.echo(f"  {entry['day']}: {entry['session_type']}")


@cli.command(name="generate-week-structure")
@click.option(
    "--week-start",
    required=True,
    help="ISO 8601 date (YYYY-MM-DD) for the Monday this plan starts on.",
)
def generate_week_structure_command(week_start: str):
    """Generate (once) and print the structured HR-zone breakdown for an
    already-planned week — PRD #111, F19.2.

    Persists to weekly_plans.generated_structure_json. If a week already has
    a generated structure, prints it as-is without recomputing — explicit
    regeneration is `regenerate-week-structure` (F19.3), not this command's.
    """
    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    plan_repo = PlanRepository(engine)

    week = plan_repo.get_weekly_plan(week_start)
    if week is None:
        raise click.ClickException(f"no weekly plan stored for week_start_date {week_start!r}")

    if week.get("generated_structure_json"):
        structured = json.loads(week["generated_structure_json"])
        click.echo(f"Structure already generated for week starting {week_start}:")
        _print_week_structure(structured)
        return

    structured = _compute_week_structure(plan_repo, week_start, week)
    plan_repo.update_weekly_plan(week_start, generated_structure_json=json.dumps(structured))

    click.echo(f"Structure generated for week starting {week_start}:")
    _print_week_structure(structured)


def _compute_week_structure(plan_repo: PlanRepository, week_start: str, week: dict) -> list[dict]:
    """Run the actual structure-generation logic (weekly load target,
    periodisation phase, planned sessions -> per-day HR-zone structure).

    Shared by `generate-week-structure` (skip-if-exists) and
    `regenerate-week-structure` (always overwrite) so the generation step
    itself isn't duplicated between the two commands.
    """
    planned_sessions = json.loads(week["planned_sessions_json"] or "[]")
    if not planned_sessions:
        raise click.ClickException(f"no sessions planned for week_start_date {week_start!r}")

    profile = plan_repo.get_athlete_profile()
    if not profile or profile.get("max_hr") is None or profile.get("baseline_resting_hr") is None or not profile.get("sex"):
        raise click.ClickException(
            "athlete profile with max_hr, baseline_resting_hr, and sex required — "
            "run `set-athlete-profile` first."
        )

    week_start_date = _date.fromisoformat(week_start)
    month = plan_repo.get_monthly_target(week_start_date.replace(day=1).isoformat())
    weekly_load_target = (
        calculate_weekly_target(month["load_target_total"])
        if month and month.get("load_target_total")
        else 0.0
    )
    periodisation_phase = (month or {}).get("periodisation_phase") or "BASE"

    return generate_week_structure(
        planned_sessions,
        weekly_load_target,
        periodisation_phase,
        max_hr=profile["max_hr"],
        resting_hr=profile["baseline_resting_hr"],
        sex=profile["sex"],
    )


@cli.command(name="regenerate-week-structure")
@click.option(
    "--week-start",
    required=True,
    help="ISO 8601 date (YYYY-MM-DD) for the Monday this plan starts on.",
)
def regenerate_week_structure_command(week_start: str):
    """Explicitly regenerate and overwrite the structured HR-zone breakdown
    for an already-planned week — PRD #111, F19.3.

    Unlike `generate-week-structure` (persist-once/stable), this always
    re-runs generation against current inputs (weekly load target,
    periodisation phase, planned sessions) and overwrites
    weekly_plans.generated_structure_json unconditionally. This is the only
    sanctioned way to change an already-generated week's structure.

    If the week has already been pushed to intervals.icu (tracked via
    weekly_plans.pushed_event_ids_json), warns that the watch/calendar will
    be stale until the week is re-pushed with `push-week`.
    """
    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    plan_repo = PlanRepository(engine)

    week = plan_repo.get_weekly_plan(week_start)
    if week is None:
        raise click.ClickException(f"no weekly plan stored for week_start_date {week_start!r}")

    existing_event_ids = json.loads(week.get("pushed_event_ids_json") or "{}")
    if existing_event_ids:
        click.echo(
            f"Warning: week starting {week_start} was already pushed to intervals.icu — "
            "the watch/calendar will be stale until you run `push-week` again."
        )

    structured = _compute_week_structure(plan_repo, week_start, week)
    plan_repo.update_weekly_plan(week_start, generated_structure_json=json.dumps(structured))

    click.echo(f"Structure regenerated for week starting {week_start}:")
    _print_week_structure(structured)


def _print_week_structure(structured: list[dict]) -> None:
    for entry in structured:
        s = entry["structure"]
        if s["type"] == "intervals":
            click.echo(
                f"  {entry['day']}: {entry['session_type']} — "
                f"{s['rep_count']}x({s['work_min']:.0f}min@{s['work_zone']}/"
                f"{s['recovery_min']:.0f}min@{s['recovery_zone']}) "
                f"+{s['warmup_cooldown_min']:.0f}min warmup/cooldown "
                f"({s['total_duration_min']:.0f}min total)"
            )
        elif s["type"] == "single_block" and "zone" in s and "main_set_min" in s:
            click.echo(
                f"  {entry['day']}: {entry['session_type']} — "
                f"{s['main_set_min']:.0f}min@{s['zone']} "
                f"+{s['warmup_cooldown_min']:.0f}min warmup/cooldown "
                f"({s['total_duration_min']:.0f}min total)"
            )
        else:
            click.echo(f"  {entry['day']}: {entry['session_type']} — {s['duration_min']:.0f}min")


def _push_week(
    plan_repo: PlanRepository, engine, settings, week_start: str, real: bool
) -> tuple[list[dict], dict[str, str]]:
    """Push a week's generated structured plan to intervals.icu as calendar
    events — the actual push logic shared by the `push-week` CLI command
    (F19.6, #121) below and `POST /api/plan/week/push`
    (web/backend/main.py, F19.7, #123) so there's exactly one implementation
    of "push a week" (docs/adr/0023).

    One event per day. First push creates; re-pushing the same day updates
    the existing event in place (tracked via weekly_plans.pushed_event_ids_json),
    not a duplicate.

    Raises click.ClickException for any input/provider error (no stored
    plan, no generated structure, non-intervals.icu provider, no stored API
    key) or adapter failure — callers decide how to surface that (the CLI
    command lets it propagate and exit non-zero; the web endpoint catches it
    and maps it to an HTTP error).

    Returns (structured_sessions, updated_event_ids) — the caller reports
    per-day results from these rather than re-reading the row itself.
    """
    week = plan_repo.get_weekly_plan(week_start)
    if week is None:
        raise click.ClickException(f"no weekly plan stored for week_start_date {week_start!r}")

    if not week.get("generated_structure_json"):
        raise click.ClickException(
            f"no generated structure for week_start_date {week_start!r} — "
            "run `generate-week-structure` first."
        )

    structured_sessions = json.loads(week["generated_structure_json"])
    existing_event_ids = json.loads(week.get("pushed_event_ids_json") or "{}")

    profile = plan_repo.get_athlete_profile()
    adapter = _build_plan_export_adapter(engine, settings, profile, real)

    week_start_date = _date.fromisoformat(week_start)
    updated_event_ids = dict(existing_event_ids)

    for session in structured_sessions:
        day = session["day"]
        event_date = (week_start_date + timedelta(days=WEEKDAYS.index(day))).isoformat()
        try:
            event_id = adapter.push_session(event_date, session, existing_event_ids.get(day))
        except AdapterError as e:
            raise click.ClickException(str(e)) from e
        updated_event_ids[day] = event_id

    plan_repo.update_weekly_plan(week_start, pushed_event_ids_json=json.dumps(updated_event_ids))
    return structured_sessions, updated_event_ids


@cli.command(name="push-week")
@click.option(
    "--week-start",
    required=True,
    help="ISO 8601 date (YYYY-MM-DD) for the Monday this plan starts on.",
)
@click.option(
    "--real",
    is_flag=True,
    default=False,
    help="Push to the real intervals.icu API instead of the mock adapter.",
)
def push_week(week_start: str, real: bool):
    """Push a week's generated structured plan to intervals.icu as calendar
    events — PRD #111, F19.6.

    One event per day. First push creates; re-pushing the same day updates
    the existing event in place (tracked via weekly_plans.pushed_event_ids_json),
    not a duplicate.
    """
    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    plan_repo = PlanRepository(engine)

    structured_sessions, updated_event_ids = _push_week(plan_repo, engine, settings, week_start, real)

    for session in structured_sessions:
        day = session["day"]
        click.echo(f"  {day}: pushed (event {updated_event_ids[day]})")

    click.echo(f"Pushed {len(structured_sessions)} sessions for week starting {week_start}.")


@cli.command(name="set-monthly-target")
@click.option(
    "--month-start-date",
    required=True,
    help="ISO 8601 date for the first day of the month, e.g. 2026-08-01.",
)
@click.option(
    "--periodisation-phase",
    type=click.Choice(PERIODISATION_PHASES),
    help="Training block phase for this month.",
)
@click.option(
    "--load-target-total",
    type=float,
    help="Planned total training load for the month.",
)
@click.option(
    "--race-date",
    default=None,
    help="ISO 8601 date of the target race this block is building toward, if any.",
)
@click.option(
    "--show",
    is_flag=True,
    default=False,
    help="Print the currently stored target for --month-start-date instead of writing.",
)
def set_monthly_target(
    month_start_date: str,
    periodisation_phase: str | None,
    load_target_total: float | None,
    race_date: str | None,
    show: bool,
):
    """Set (or view) a training block's monthly target: periodisation phase,
    total load target, and race date. Writes via
    PlanRepository.upsert_monthly_target()."""
    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    repo = PlanRepository(engine)

    if show:
        target = repo.get_monthly_target(month_start_date)
        if target is None:
            click.echo(f"No monthly target stored for {month_start_date}.")
            return
        click.echo(f"Month start date: {target['month_start_date']}")
        click.echo(f"Periodisation phase: {target['periodisation_phase']}")
        click.echo(f"Load target total: {target['load_target_total']}")
        click.echo(f"Race date: {target['race_date']}")
        return

    if periodisation_phase is None or load_target_total is None:
        raise click.ClickException(
            "--periodisation-phase and --load-target-total are required "
            "(unless --show is passed to view an existing target)."
        )

    created = repo.upsert_monthly_target(
        month_start_date, periodisation_phase, load_target_total, race_date
    )
    if created:
        click.echo(f"Monthly target created for {month_start_date}.")
    else:
        click.echo(f"Monthly target updated for {month_start_date}.")


@cli.command(name="set-race-goal")
@click.option(
    "--distance",
    type=click.Choice(RACE_DISTANCE_CHOICES),
    help="Goal race distance.",
)
@click.option(
    "--race-date",
    help="ISO 8601 date (YYYY-MM-DD) of the target race.",
)
@click.option(
    "--replace",
    is_flag=True,
    default=False,
    help="Mark the currently ACTIVE race goal ABANDONED and create this one in its "
    "place. Without this flag, set-race-goal refuses to create a second ACTIVE goal.",
)
@click.option(
    "--show",
    is_flag=True,
    default=False,
    help="Print the currently active race goal instead of writing.",
)
def set_race_goal(distance: str | None, race_date: str | None, replace: bool, show: bool):
    """Set (or view) the athlete's active race goal: a target distance and
    race date. PRD #138's future macro-plan accept step (F20.3) will use
    this to seed monthly targets — this ticket (F20.1) only stores and
    shows the goal itself. At most one ACTIVE goal at a time
    (docs/adr/0023, single-athlete system) — pass --replace to explicitly
    supersede an existing one rather than silently overwriting it."""
    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    repo = PlanRepository(engine)

    if show:
        goal = repo.get_active_race_goal()
        if goal is None:
            click.echo("No active race goal.")
            return
        click.echo(f"Goal distance: {goal['goal_distance']}")
        click.echo(f"Target race date: {goal['target_race_date']}")
        click.echo(f"Status: {goal['status']}")
        return

    if distance is None or race_date is None:
        raise click.ClickException(
            "--distance and --race-date are required (unless --show is passed "
            "to view the active goal)."
        )

    try:
        _date.fromisoformat(race_date)
    except ValueError as e:
        raise click.ClickException(
            f"--race-date must be an ISO 8601 date (YYYY-MM-DD): {race_date!r}"
        ) from e

    existing = repo.get_active_race_goal()
    if existing is not None:
        if not replace:
            raise click.ClickException(
                f"an ACTIVE race goal already exists ({existing['goal_distance']} on "
                f"{existing['target_race_date']}) — pass --replace to supersede it."
            )
        repo.update_race_goal_status(existing["id"], "ABANDONED")

    repo.insert_race_goal(goal_distance=distance, target_race_date=race_date, status="ACTIVE")
    click.echo(f"Race goal set: {distance} on {race_date}.")


@cli.command(name="preview-macro-plan")
@click.option(
    "--distance", required=True, type=click.Choice(RACE_DISTANCE_CHOICES), help="Goal race distance."
)
@click.option(
    "--race-date", required=True, help="ISO 8601 date (YYYY-MM-DD) of the target race."
)
@click.option(
    "--today",
    default=None,
    help="ISO 8601 date to treat as 'today' (defaults to the actual current date, UTC).",
)
def preview_macro_plan_command(distance: str, race_date: str, today: str | None):
    """Preview the proposed macro training-block plan for a goal distance
    and race date — phase and load target for every month from today
    through the race, grounded in the athlete's recent training history
    (PRD #138, F20.3). Writes nothing; run accept-macro-plan with the same
    flags to write it."""
    if today is None:
        today = datetime.now(timezone.utc).date().isoformat()

    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    plan_repo = PlanRepository(engine)
    metrics_repo = MetricsRepository(engine)

    try:
        preview = preview_macro_plan(plan_repo, metrics_repo, distance, race_date, today)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    click.echo(
        f"Goal: {preview['goal_distance']} on {preview['race_date']} "
        f"({preview['weeks_to_race']} weeks away)"
    )
    click.echo(f"Current phase: {preview['current_phase']}")
    click.echo(f"Estimated current weekly load: {preview['current_weekly_load_au']} AU")
    click.echo()
    for month in preview["months"]:
        note = " (already set — accept would leave this month as-is)" if month["already_set"] else ""
        click.echo(
            f"  {month['month_start_date']}: {month['periodisation_phase']}, "
            f"{month['load_target_total']} AU/month{note}"
        )


@cli.command(name="accept-macro-plan")
@click.option(
    "--distance", required=True, type=click.Choice(RACE_DISTANCE_CHOICES), help="Goal race distance."
)
@click.option(
    "--race-date", required=True, help="ISO 8601 date (YYYY-MM-DD) of the target race."
)
@click.option(
    "--replace",
    is_flag=True,
    default=False,
    help="Abandon the currently ACTIVE race goal and replace it with this one — same "
    "collision policy as set-race-goal --replace.",
)
@click.option(
    "--today",
    default=None,
    help="ISO 8601 date to treat as 'today' (defaults to the actual current date, UTC).",
)
def accept_macro_plan_command(distance: str, race_date: str, replace: bool, today: str | None):
    """Generate and immediately write the macro training-block plan: sets
    the race goal and seeds monthly_targets for every recommended month,
    leaving any month the athlete has already customized untouched (PRD
    #138, F20.3). Re-derives the proposal itself from --distance/--race-date
    rather than depending on a prior preview-macro-plan call — run
    preview-macro-plan first if you want to review before writing."""
    if today is None:
        today = datetime.now(timezone.utc).date().isoformat()

    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    plan_repo = PlanRepository(engine)
    metrics_repo = MetricsRepository(engine)

    try:
        result = accept_macro_plan(
            plan_repo, metrics_repo, distance, race_date, today, replace=replace
        )
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"Race goal set: {distance} on {race_date}.")
    for month in result["months"]:
        if month["written"]:
            action = "created" if month["created"] else "updated"
            click.echo(
                f"  {month['month_start_date']}: {action} → {month['periodisation_phase']}, "
                f"{month['load_target_total']} AU/month"
            )
        else:
            click.echo(f"  {month['month_start_date']}: left as-is (already set by the athlete)")


@cli.command(name="regenerate-macro-plan")
@click.option(
    "--distance",
    required=True,
    type=click.Choice(RACE_DISTANCE_CHOICES),
    help="Goal race distance — pass the same value as before if only the race date changed.",
)
@click.option(
    "--race-date",
    required=True,
    help="ISO 8601 date (YYYY-MM-DD) of the target race — pass the same value as before if "
    "only the distance changed.",
)
@click.option(
    "--today",
    default=None,
    help="ISO 8601 date to treat as 'today' (defaults to the actual current date, UTC).",
)
def regenerate_macro_plan_command(distance: str, race_date: str, today: str | None):
    """Explicitly re-run the macro plan after the athlete's goal distance
    or race date changes mid-block (PRD #138, F20.4) — only ever touches
    future months; the current and past months are left alone regardless
    of what the new template proposes. Requires an existing ACTIVE race
    goal — run accept-macro-plan first if there isn't one yet.

    Warns per month if week-level structure was already generated (or
    pushed to intervals.icu) under the old target — that structure is now
    stale until `regenerate-week-structure` (and `push-week`) are re-run
    for the affected weeks."""
    if today is None:
        today = datetime.now(timezone.utc).date().isoformat()

    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    plan_repo = PlanRepository(engine)
    metrics_repo = MetricsRepository(engine)

    try:
        result = regenerate_macro_plan(plan_repo, metrics_repo, distance, race_date, today)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"Race goal updated: {distance} on {race_date}.")
    for month in result["months"]:
        if month["written"]:
            action = "created" if month["created"] else "updated"
            click.echo(
                f"  {month['month_start_date']}: {action} → {month['periodisation_phase']}, "
                f"{month['load_target_total']} AU/month"
            )
            if month["stale_week_structure"]:
                click.echo(
                    "    Warning: week-level structure was already generated (or pushed to "
                    "intervals.icu) for this month under the old target — it's stale until "
                    "you re-run regenerate-week-structure (and push-week) for those weeks."
                )
        else:
            click.echo(f"  {month['month_start_date']}: left as-is (already set by the athlete)")


@cli.command(name="set-athlete-profile")
@click.option("--max-hr", type=int, help="Max HR (bpm) — feeds TRIMP load calculation and zones.")
@click.option(
    "--baseline-resting-hr",
    type=int,
    help=(
        "Fallback resting HR (bpm) for TRIMP load calculation, only used when a "
        "session's date has no WHOOP resting HR recorded (docs/adr/0024)."
    ),
)
@click.option("--sex", type=click.Choice(ATHLETE_SEX_CHOICES), help="Feeds TRIMP's exponential weighting constant.")
@click.option(
    "--activity-sync-provider",
    type=click.Choice(ACTIVITY_SYNC_PROVIDER_CHOICES),
    help=(
        "Which adapter `sync-session --real` dispatches to (docs/adr/0025). "
        "Defaults to STRAVA if never set. Run `connect-intervals-icu` first "
        "if switching to INTERVALS_ICU."
    ),
)
@click.option(
    "--show", is_flag=True, default=False, help="Print the currently stored profile instead of writing."
)
def set_athlete_profile(
    max_hr: int | None,
    baseline_resting_hr: int | None,
    sex: str | None,
    activity_sync_provider: str | None,
    show: bool,
):
    """Set (or view) the athlete's profile: max HR, a fallback resting HR,
    sex (docs/adr/0024), and the active activity-sync provider
    (docs/adr/0025). Single global row — this is a single-user system
    (docs/adr/0023). Writes via PlanRepository.insert_athlete_profile()
    on first write, update_athlete_profile() thereafter."""
    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    repo = PlanRepository(engine)

    if show:
        profile = repo.get_athlete_profile()
        if profile is None:
            click.echo("No athlete profile stored.")
            return
        click.echo(f"Max HR: {profile['max_hr']}")
        click.echo(f"Baseline resting HR: {profile['baseline_resting_hr']}")
        click.echo(f"Sex: {profile['sex']}")
        click.echo(
            f"Activity sync provider: "
            f"{profile['activity_sync_provider'] or DEFAULT_ACTIVITY_SYNC_PROVIDER}"
        )
        return

    existing = repo.get_athlete_profile()
    fields = {
        "max_hr": max_hr if max_hr is not None else (existing or {}).get("max_hr"),
        "baseline_resting_hr": (
            baseline_resting_hr
            if baseline_resting_hr is not None
            else (existing or {}).get("baseline_resting_hr")
        ),
        "sex": sex if sex is not None else (existing or {}).get("sex"),
        "activity_sync_provider": (
            activity_sync_provider
            if activity_sync_provider is not None
            else (existing or {}).get("activity_sync_provider")
        ),
    }

    if existing is None:
        repo.insert_athlete_profile(**fields)
        click.echo("Athlete profile created.")
    else:
        repo.update_athlete_profile(**fields)
        click.echo("Athlete profile updated.")


def _resolve_todays_session(plan_repo, date_str, session_type_flag):
    """Find today's scheduled session in the current week's plan (#41's
    planned_sessions_json), falling back to --session-type if no plan
    covers this date at all (first-ever run, or the athlete hasn't
    planned this week yet)."""
    d = _date.fromisoformat(date_str)
    week_start = (d - timedelta(days=d.weekday())).isoformat()
    weekday_name = WEEKDAYS[d.weekday()]

    week_plan = plan_repo.get_weekly_plan(week_start)
    week_sessions = []
    if week_plan and week_plan["planned_sessions_json"]:
        week_sessions = json.loads(week_plan["planned_sessions_json"])

    todays_entry = next((s for s in week_sessions if s["day"] == weekday_name), None)
    if todays_entry is not None:
        return todays_entry["session_type"], week_plan, week_sessions, weekday_name, week_start

    if session_type_flag is not None:
        return session_type_flag, week_plan, week_sessions, weekday_name, week_start

    raise click.ClickException(
        f"No weekly plan covers {weekday_name} of the week starting {week_start} — "
        "run `plan-week` first, or pass --session-type as a fallback."
    )


def _tomorrow_session_type(week_sessions, weekday_name):
    """Best-effort lookup for daily_engine's Recovery/Rest CNS-primer check.
    Only resolvable when tomorrow falls in the same week's plan — Sunday's
    "tomorrow" crosses into next week's (possibly not-yet-planned) row, so
    that case is left as None rather than guessed at."""
    idx = WEEKDAYS.index(weekday_name)
    if idx == len(WEEKDAYS) - 1:
        return None
    tomorrow_name = WEEKDAYS[idx + 1]
    entry = next((s for s in week_sessions if s["day"] == tomorrow_name), None)
    return entry["session_type"] if entry else None


def _sessions_remaining(week_sessions, weekday_name):
    today_idx = WEEKDAYS.index(weekday_name)
    remaining = []
    for s in week_sessions:
        idx = WEEKDAYS.index(s["day"])
        if idx < today_idx:
            continue
        label = s["session_type"] + (" (today)" if idx == today_idx else "")
        remaining.append(label)
    return remaining


def _resolve_athlete_context(plan_repo, date_str):
    """training_phase/race_date/weeks_to_race from the month's monthly_target
    (#48) — gracefully empty if the athlete hasn't set one up yet."""
    d = _date.fromisoformat(date_str)
    month_start = d.replace(day=1).isoformat()
    target = plan_repo.get_monthly_target(month_start)
    if target is None:
        return {"training_phase": None, "race_date": None, "weeks_to_race": None}

    race_date = target["race_date"]
    weeks_to_race = None
    if race_date:
        weeks_to_race = max((_date.fromisoformat(race_date) - d).days // 7, 0)

    return {
        "training_phase": target["periodisation_phase"],
        "race_date": race_date,
        "weeks_to_race": weeks_to_race,
    }


def run_decision_pipeline(
    plan_repo,
    metrics_repo,
    date_str: str,
    resolved_session_type: str,
    whoop_payload,
    fixed_answers: dict,
    adaptive_answers: dict,
    health_result: dict,
    week_plan: dict | None,
    week_sessions: list,
    weekday_name: str,
) -> tuple[dict, dict]:
    """Steps 5-9 of the morning pipeline, shared by the CLI's `morning`
    command and the web backend's `POST /api/morning/decision` (F17.2,
    #84) — the exact API Contract §4.3 Decision Context shape must not
    drift between the two surfaces, so this is the one place it's built.

    `whoop_payload` only needs `.whoop_recovery_pct`/`.whoop_hrv_ms`/
    `.whoop_rhr_bpm`/`.whoop_strain` attributes — a `WhoopDailyPayload`
    (CLI, freshly fetched) or a `types.SimpleNamespace` built from an
    already-persisted `daily_metrics` row (web, since the fetch happened
    in an earlier request) both satisfy this duck-typed interface.

    Persists the bare Decision Output via `insert_decision()` before
    returning — a crash or Ollama failure downstream must never lose the
    decision itself (ADR-0001).

    Returns `(decision_result, decision_context)`.
    """
    hrv_30d_avg_ms = resolve_hrv_30d_avg_for_classification(
        metrics_repo, date_str, whoop_payload.whoop_hrv_ms
    )

    classification = classify_daily_inputs(
        whoop_payload, fixed_answers["muscle_soreness"], hrv_30d_avg_ms
    )

    tomorrow_session_type = _tomorrow_session_type(week_sessions, weekday_name)
    decision_result = make_decision(
        session_type=resolved_session_type,
        recovery_band=classification["recovery_band"],
        hrv_signal=classification["hrv_delta_band"],
        soreness_band=classification["soreness_band"],
        override_triggered=health_result["override_triggered"],
        override_reasons=health_result["override_reasons"] or None,
        tomorrow_session_type=tomorrow_session_type,
    )

    rationale_dict = {
        "recovery_zone": (
            f"{classification['recovery_band'].value} ({classification['recovery_pct']}%)"
        ),
        "hrv_signal": (
            f"{classification['hrv_delta_band'].value} "
            f"({classification['hrv_delta_ms']:+.1f}ms vs 30d avg)"
        ),
        "soreness_level": (
            f"{classification['soreness_band'].value} ({fixed_answers['muscle_soreness']}/5)"
        ),
        "rule_applied": decision_result["rationale"] or "(no additional rationale)",
        # #132: kept alongside the human-readable breakdown above so
        # GET /api/morning/context's rehydration path can reconstruct the
        # exact POST /api/morning/decision response shape (rationale as
        # decision_result gave it, not the "(no additional rationale)"
        # display fallback) from this one stored rationale_json blob.
        "rationale": decision_result["rationale"],
        "override_triggered": health_result["override_triggered"],
        "override_reasons": health_result["override_reasons"],
        "check_recovery_week_trigger": decision_result["check_recovery_week_trigger"],
    }

    plan_repo.insert_decision(
        date=date_str,
        scheduled_session=resolved_session_type,
        recommendation=decision_result["recommendation"],
        rationale_json=json.dumps(rationale_dict),
    )

    decision_context = {
        "date": date_str,
        "athlete_context": _resolve_athlete_context(plan_repo, date_str),
        "todays_plan": {
            "scheduled_session": resolved_session_type,
            "session_description": SESSION_DESCRIPTIONS[resolved_session_type],
        },
        "biometrics": {
            "whoop_recovery_pct": whoop_payload.whoop_recovery_pct,
            "whoop_hrv_ms": whoop_payload.whoop_hrv_ms,
            "hrv_30d_avg_ms": hrv_30d_avg_ms,
            "hrv_delta_ms": classification["hrv_delta_ms"],
            "hrv_signal": classification["hrv_delta_band"].value,
            "whoop_rhr_bpm": whoop_payload.whoop_rhr_bpm,
            "whoop_strain_so_far": whoop_payload.whoop_strain,
        },
        "morning_check": {
            "muscle_soreness": fixed_answers["muscle_soreness"],
            "subjective_energy": fixed_answers["subjective_energy"],
            "sleep_quality_felt": fixed_answers["sleep_quality_felt"],
            "adaptive_checks": adaptive_answers,
        },
        "decision": {
            "recommendation": decision_result["recommendation"],
            "rationale": rationale_dict,
        },
        "weekly_context": {
            "week_status": week_plan["week_status"] if week_plan else None,
            "load_actual": week_plan["load_actual"] if week_plan else None,
            "load_target": week_plan["load_target"] if week_plan else None,
            "sessions_remaining": _sessions_remaining(week_sessions, weekday_name),
        },
    }

    return decision_result, decision_context


def persist_decision_with_explanation(plan_repo, date_str, resolved_session_type, decision_result, decision_context, llm_explanation) -> None:
    """The second, fuller decisions row inserted once Ollama succeeds —
    decisions is append-only (ADR-0003/0007); get_decision() returns the
    latest by created_at, so this becomes the record of what the athlete
    actually saw, while the bare pre-Ollama row remains the crash-safe
    one. Shared by the CLI and the web backend (F17.2, #84).

    #132: also stores the full decision_context verbatim, so a later
    GET /api/morning/context can rehydrate today's Decision Output (and
    the Explanation Layer can answer further follow-ups against the exact
    context the original explanation was generated from) without
    reconstructing it from other tables."""
    plan_repo.insert_decision(
        date=date_str,
        scheduled_session=resolved_session_type,
        recommendation=decision_result["recommendation"],
        rationale_json=json.dumps(decision_context["decision"]["rationale"]),
        llm_explanation=llm_explanation,
        decision_context_json=json.dumps(decision_context),
    )


@cli.command()
@click.option(
    "--date",
    default=None,
    help="ISO 8601 date to run for (defaults to today, UTC).",
)
@click.option(
    "--session-type",
    type=click.Choice(SESSION_TYPES),
    default=None,
    help="Fallback session type, only used if no weekly plan covers --date.",
)
@click.option(
    "--real",
    is_flag=True,
    default=False,
    help="Use RealWhoopAdapter + RealOllamaAdapter instead of the mocks.",
)
def morning(date: str | None, session_type: str | None, real: bool):
    """The full morning routine (API Contract §4.3), tracer-bullet for
    F01-F11.4: fetch WHOOP, persist it, resolve today's scheduled session
    from the current week's plan, run the interactive health check,
    compute the 30-day HRV baseline, classify, run the Daily Decision
    Engine, persist the Decision Output, then call Ollama for a
    natural-language explanation.

    Mock WHOOP + Ollama by default (safe dry run, deterministic, no
    network calls); --real hits the live WHOOP API and a local Ollama
    instance.
    """
    if date is None:
        date = datetime.now(timezone.utc).date().isoformat()

    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    metrics_repo = MetricsRepository(engine)
    plan_repo = PlanRepository(engine)

    # 1. Fetch real WHOOP data
    if real:
        if not settings.whoop_client_id or not settings.whoop_client_secret:
            raise click.ClickException("WHOOP_CLIENT_ID / WHOOP_CLIENT_SECRET not set in .env.")
        token_repo = TokenRepository(engine, settings.apex_encryption_key)
        whoop_adapter = RealWhoopAdapter(
            token_repo, settings.whoop_client_id, settings.whoop_client_secret
        )
    else:
        whoop_adapter = MockWhoopAdapter()

    try:
        whoop_payload = whoop_adapter.get_daily_payload(date)
    except AdapterError as e:
        raise click.ClickException(str(e)) from e

    # 2. Persist it (#43)
    metrics_repo.upsert_daily_metrics(
        date,
        whoop_recovery_pct=whoop_payload.whoop_recovery_pct,
        whoop_hrv_ms=whoop_payload.whoop_hrv_ms,
        whoop_rhr_bpm=whoop_payload.whoop_rhr_bpm,
        whoop_strain=whoop_payload.whoop_strain,
        whoop_sleep_hours=whoop_payload.whoop_sleep_hours,
    )

    # 3. Look up today's scheduled session from the current week's plan (#41)
    resolved_session_type, week_plan, week_sessions, weekday_name, week_start = (
        _resolve_todays_session(plan_repo, date, session_type)
    )

    # 4. Run the interactive morning health check for that session type (#42)
    fixed_answers = {}
    for key, text in FIXED_QUESTIONS:
        fixed_answers[key] = click.prompt(text, type=click.IntRange(1, 5))
    adaptive_answers = {}
    for question in get_adaptive_questions(resolved_session_type):
        adaptive_answers[question.key] = click.prompt(question.text, type=click.IntRange(1, 5))

    health_result = evaluate_health_check(resolved_session_type, fixed_answers, adaptive_answers)
    if health_result["override_triggered"]:
        click.echo("Override triggered:")
        for reason in health_result["override_reasons"]:
            click.echo(f"  - {reason}")
    persist_health_check(metrics_repo, date, health_result)

    # 5-9. HRV baseline, classify, decide, persist the bare Decision Output,
    # assemble the Decision Context (API Contract §4.3) — shared with the
    # web backend's POST /api/morning/decision (F17.2, #84).
    try:
        decision_result, decision_context = run_decision_pipeline(
            plan_repo,
            metrics_repo,
            date,
            resolved_session_type,
            whoop_payload,
            fixed_answers,
            adaptive_answers,
            health_result,
            week_plan,
            week_sessions,
            weekday_name,
        )
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    ollama_adapter = RealOllamaAdapter() if real else MockOllamaAdapter()
    explanation_result = ollama_adapter.explain(decision_context)

    if not explanation_result.degraded:
        persist_decision_with_explanation(
            plan_repo,
            date,
            resolved_session_type,
            decision_result,
            decision_context,
            explanation_result.explanation,
        )

    # 10. Print the recommendation, rationale, and explanation (plus any
    # WARN/INFO banner if Ollama degraded) — the recommendation always
    # prints even when the explanation doesn't (§6.3).
    click.echo(f"Recommendation: {decision_result['recommendation']}")
    click.echo(f"Rationale: {decision_result['rationale'] or '(none)'}")
    if decision_result["check_recovery_week_trigger"]:
        click.echo("[Flag: check_recovery_week_trigger]")
    if explanation_result.banner:
        click.echo(f"[{explanation_result.severity}] {explanation_result.banner}")
    if explanation_result.explanation:
        click.echo(f"Explanation: {explanation_result.explanation}")

    # 11. Conversational follow-up loop (PRD / ADR-0001) — only offered when
    # there's an explanation to follow up on; if Ollama never produced one,
    # ask_followup() would have nothing to anchor the prior-assistant-turn
    # message to.
    if explanation_result.explanation:
        _run_followup_loop(ollama_adapter, decision_context, explanation_result.explanation)


def _run_followup_loop(ollama_adapter, decision_context: dict, prior_explanation: str) -> None:
    while True:
        question = click.prompt(
            "Ask a follow-up (why? what if I do it anyway?), or press Enter to finish",
            default="",
            show_default=False,
        )
        if not question:
            return

        followup_result = ollama_adapter.ask_followup(
            decision_context, prior_explanation, question
        )
        if followup_result.banner:
            click.echo(f"[{followup_result.severity}] {followup_result.banner}")
        if followup_result.explanation:
            click.echo(followup_result.explanation)
            prior_explanation = followup_result.explanation


@cli.command(name="weekly-summary")
@click.option(
    "--week-start",
    required=True,
    help="ISO 8601 date (YYYY-MM-DD) for the Monday of the week to summarize.",
)
@click.option(
    "--today",
    default=None,
    help=(
        "ISO 8601 date to treat as 'today' for day-passed / end-of-week checks "
        "(defaults to the actual current date, UTC)."
    ),
)
def weekly_summary(week_start: str, today: str | None):
    """Run weekly_engine.run_weekly_adaptation() against a real week's
    accumulated decisions/activities/session_scores, persist week_status/
    adapted_plan_json/load_actual (and a derived load_target, if a monthly
    target exists) back to weekly_plans, and print a human-readable summary.

    A missed KEY session (HIIT/Threshold) is auto-detected — a plan day
    whose date has passed with no activity synced for it, and not already
    recorded in skipped_sessions — and fed into the engine's single-skip-
    per-run reschedule/write-off logic. Only the chronologically-earliest
    newly-missed KEY session is handled per run; running this again after
    another day passes picks up the next one.
    """
    if today is None:
        today = datetime.now(timezone.utc).date().isoformat()

    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    plan_repo = PlanRepository(engine)
    metrics_repo = MetricsRepository(engine)

    week = plan_repo.get_weekly_plan(week_start)
    if week is None:
        raise click.ClickException(
            f"no weekly_plans row for week_start_date {week_start!r} — run `plan-week` first."
        )

    week_start_date = _date.fromisoformat(week_start)
    week_end_date = week_start_date + timedelta(days=6)
    today_date = _date.fromisoformat(today)

    # Read the week's decisions — one per day, used below to surface
    # explicit ABORTs in the summary.
    decisions_by_day = {}
    for i, day_name in enumerate(WEEKDAYS):
        day_date = (week_start_date + timedelta(days=i)).isoformat()
        decision = plan_repo.get_decision(day_date)
        if decision is not None:
            decisions_by_day[day_name] = decision

    # Read the week's activities + their session scores.
    week_activities = metrics_repo.get_activities_range(week_start, week_end_date.isoformat())
    daily_rows = metrics_repo.get_daily_metrics_range(week_start, week_end_date.isoformat())
    resting_hr_by_date = {
        row["date"]: row["whoop_rhr_bpm"] for row in daily_rows if row["whoop_rhr_bpm"] is not None
    }
    profile = plan_repo.get_athlete_profile()
    try:
        load_actual = sum(
            load_au_for_activity(
                a,
                resting_hr=resting_hr_by_date.get(a["date"])
                or (profile.get("baseline_resting_hr") if profile else None),
                max_hr=profile.get("max_hr") if profile else None,
                sex=profile.get("sex") if profile else None,
            )
            for a in week_activities
        )
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    activities_by_date: dict[str, list] = {}
    for activity in week_activities:
        activities_by_date.setdefault(activity["date"], []).append(activity)

    session_scores = []
    for activity in week_activities:
        score = metrics_repo.get_session_score(activity["id"])
        if score is not None:
            session_scores.append(score)

    # Auto-detect the earliest newly-missed KEY session.
    effective_sessions = json.loads(week["adapted_plan_json"] or week["planned_sessions_json"] or "[]")
    already_skipped_days = {s["original_day"] for s in json.loads(week["skipped_sessions"] or "[]")}

    key_session_skipped_type = None
    key_session_skipped_day = None
    for session in effective_sessions:
        if session["session_type"] not in KEY_SESSION_TYPES:
            continue
        if session["day"] in already_skipped_days:
            continue
        session_date = (week_start_date + timedelta(days=WEEKDAYS.index(session["day"]))).isoformat()
        if session_date >= today:
            continue
        if session_date in activities_by_date:
            continue
        key_session_skipped_type = session["session_type"]
        key_session_skipped_day = session["day"]
        break

    result = run_weekly_adaptation(
        plan_repo,
        metrics_repo,
        week_start,
        today=today,
        key_session_skipped_type=key_session_skipped_type,
        key_session_skipped_day=key_session_skipped_day,
        end_of_week_reached=today_date > week_end_date,
    )

    update_fields = {"load_actual": load_actual}
    month = plan_repo.get_monthly_target(week_start_date.replace(day=1).isoformat())
    if month and month.get("load_target_total"):
        update_fields["load_target"] = calculate_weekly_target(month["load_target_total"])
    plan_repo.update_weekly_plan(week_start, **update_fields)
    load_target = update_fields.get("load_target", week["load_target"])

    click.echo(f"Week starting {week_start}: {result['week_status']}")
    if load_target:
        click.echo(f"Load actual: {load_actual:.1f} AU / target {load_target:.1f} AU")
    else:
        click.echo(f"Load actual: {load_actual:.1f} AU (no monthly target set)")

    if result["diff"]:
        click.echo("Adapted sessions:")
        for change in result["diff"]:
            click.echo(f"  {change['day']}: {change['from']} -> {change['to']}")

    if result["skipped_sessions"]:
        click.echo("Skipped sessions:")
        for skip in result["skipped_sessions"]:
            click.echo(f"  {skip['original_day']} {skip['session_type']} — {skip['disposition']}")

    aborted_days = [day for day, d in decisions_by_day.items() if d["recommendation"] == "ABORT"]
    if aborted_days:
        click.echo(f"Daily engine recommended ABORT on: {', '.join(aborted_days)}")

    execution_scores = [
        s["execution_score"] for s in session_scores if s.get("execution_score") is not None
    ]
    if execution_scores:
        avg = sum(execution_scores) / len(execution_scores)
        click.echo(
            f"Average execution score this week: {avg:.1f} ({len(execution_scores)} scored session(s))"
        )


@cli.command(name="monthly-summary")
@click.option(
    "--month-start-date",
    required=True,
    help="ISO 8601 date for the first day of the month, e.g. 2026-08-01.",
)
@click.option(
    "--today",
    default=None,
    help=(
        "ISO 8601 date to treat as 'today' for days-elapsed-in-month accounting "
        "(defaults to the actual current date, UTC)."
    ),
)
def monthly_summary(month_start_date: str, today: str | None):
    """Run monthly_engine.run_monthly_review() against a real month's
    accumulated weekly_plans/activities/session_scores/daily_metrics data,
    persist load_actual_total/hrv_trend_json/month_summary_json back to
    monthly_targets, and print a human-readable summary (Logic Spec §5.3)."""
    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    plan_repo = PlanRepository(engine)
    metrics_repo = MetricsRepository(engine)

    try:
        summary = run_monthly_review(plan_repo, metrics_repo, month_start_date, today=today)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"{summary['month']} ({summary['periodisation_phase']})")
    click.echo(
        f"Load: {summary['load_actual_au']:.1f} / {summary['load_target_au']:.1f} AU "
        f"({summary['load_pct']}%) — {summary['load_status']}"
    )
    click.echo(f"HRV trend: {summary['hrv_trend']} (weekly avgs: {summary['hrv_weekly_avgs_ms']})")
    click.echo(
        f"Sessions: {summary['sessions_completed']} completed, "
        f"{summary['sessions_skipped']} skipped ({summary['sessions_written_off']} written off), "
        f"{summary['recovery_weeks']} recovery week(s)"
    )
    click.echo(f"Session quality avg: {summary['session_quality_avg']}")
    click.echo(
        f"Overpush flags: {summary['overpush_flags']}, "
        f"Underpush flags: {summary['underpush_flags']}"
    )

    top = summary["top_execution_session"]
    if top:
        click.echo(
            f"Best session: {top.get('session_type', 'unknown')} "
            f"(score {top['execution_score']:.1f})"
        )
    worst = summary["worst_execution_session"]
    if worst:
        click.echo(
            f"Worst session: {worst.get('session_type', 'unknown')} "
            f"(score {worst['execution_score']:.1f})"
        )

    if summary["key_observations"]:
        click.echo("Key observations:")
        for observation in summary["key_observations"]:
            click.echo(f"  - {observation}")

    click.echo(f"Next month: {summary['next_month_recommendation']}")


if __name__ == "__main__":
    cli()
