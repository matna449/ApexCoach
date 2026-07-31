"""CLI entry point — command group. See docs/adr/0008."""

from datetime import datetime, timedelta, timezone

import click

from apex_coach.adapters.errors import AdapterError
from apex_coach.adapters.strava_adapter import MockStravaAdapter
from apex_coach.adapters.whoop_adapter import (
    MockWhoopAdapter,
    RealWhoopAdapter,
    run_authorization_flow,
)
from apex_coach.config.settings import get_settings
from apex_coach.db.engine import create_engine
from apex_coach.db.schema import metadata
from apex_coach.db.token_repository import TokenRepository
from apex_coach.engines.daily_engine import make_decision
from apex_coach.orchestrator.orchestrator import HRVDeltaBand, RecoveryBand, SorenessBand
from apex_coach.services.zone_calculator import calculate_zones

ZONE_LABELS = {
    "zone1": "Zone 1 (Recovery)",
    "zone2": "Zone 2 (Aerobic base)",
    "zone3": "Zone 3 (Tempo)",
    "zone4": "Zone 4 (Threshold)",
    "zone5": "Zone 5 (VO2max)",
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
        tokens = run_authorization_flow(
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


@cli.command(name="strava-smoke")
@click.option(
    "--since-ts",
    type=int,
    default=0,
    help="Unix timestamp — fetch activities newer than this (defaults to 0, all).",
)
def strava_smoke(since_ts: int):
    """Fetch (mock) recent Strava activities and print them. No network calls."""
    adapter = MockStravaAdapter()
    activities = adapter.get_new_activities(since_ts)

    for activity in activities:
        click.echo(f"{activity.name} ({activity.type})")
        click.echo(f"  Distance: {activity.distance} m")
        click.echo(f"  Duration: {activity.elapsed_time} s")
        hr = activity.average_heartrate
        click.echo(f"  Avg HR: {hr} bpm" if hr is not None else "  Avg HR: n/a")
        pace = activity.pace_sec_per_km
        click.echo(f"  Pace: {pace:.1f} sec/km" if pace is not None else "  Pace: n/a")
        click.echo(f"  Elevation gain: {activity.total_elevation_gain} m")


@cli.command()
@click.option(
    "--session-type",
    required=True,
    type=click.Choice(
        ["HIIT", "Threshold", "Zone2_Long", "Zone2_Short", "Strength", "Recovery", "Rest"]
    ),
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


if __name__ == "__main__":
    cli()
