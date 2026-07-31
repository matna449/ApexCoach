"""CLI entry point — command group. See docs/adr/0008."""

import json
from datetime import datetime, timedelta, timezone

import click

from apex_coach.adapters.errors import AdapterError
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
from apex_coach.engines.daily_engine import make_decision
from apex_coach.orchestrator.orchestrator import HRVDeltaBand, RecoveryBand, SorenessBand
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

# score_session's vocabulary minus Rest — Rest has no structured activity to
# sync (session_scorer.py §2.4/§6.1).
SCORABLE_SESSION_TYPES = [
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

WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


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


@cli.command(name="sync-session")
@click.option(
    "--session-type",
    required=True,
    type=click.Choice(SCORABLE_SESSION_TYPES),
    help="Which session this activity was meant to be — resolves the intended HR zone.",
)
@click.option("--max-hr", type=int, required=True, help="Max HR (bpm), for zone resolution.")
@click.option(
    "--resting-hr", type=int, required=True, help="Resting HR (bpm), for zone resolution."
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
    "--real", is_flag=True, default=False, help="Use RealStravaAdapter instead of the mock."
)
def sync_session(
    session_type: str,
    max_hr: int,
    resting_hr: int,
    since_ts: int,
    planned_load: float | None,
    rpe: int | None,
    real: bool,
):
    """Close the loop after a real session: fetch new Strava activities,
    let the athlete pick one, compute load_score, prompt for RPE, score
    execution against zone boundaries, and persist both the activity and
    the session score.

    Re-running against an activity that was already synced upserts the
    activity row (matched on strava_id) rather than erroring, and appends
    a fresh session_scores row (append-only, ADR-0006).
    """
    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    repo = MetricsRepository(engine)

    if real:
        if not settings.strava_client_id or not settings.strava_client_secret:
            raise click.ClickException("STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET not set in .env.")
        token_repo = TokenRepository(engine, settings.apex_encryption_key)
        adapter = RealStravaAdapter(
            token_repo, settings.strava_client_id, settings.strava_client_secret
        )
    else:
        adapter = MockStravaAdapter()

    try:
        candidates = adapter.get_new_activities(since_ts)
    except AdapterError as e:
        raise click.ClickException(str(e)) from e

    if not candidates:
        click.echo("No new Strava activities to sync.")
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

    duration_minutes = activity.elapsed_time / 60
    try:
        if activity.type == "WeightTraining":
            load_score = calculate_load_au(activity.type, duration_minutes, rpe=rpe)
        else:
            load_score = calculate_load_au(
                activity.type,
                duration_minutes,
                avg_hr_bpm=activity.average_heartrate,
                grade_pct=activity.grade_pct,
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

    date_str = activity.start_date.date().isoformat()
    if repo.get_daily_metrics(date_str) is None:
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


if __name__ == "__main__":
    cli()
