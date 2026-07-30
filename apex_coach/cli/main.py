"""CLI entry point — command group. See docs/adr/0008."""

from datetime import datetime, timezone

import click

from apex_coach.adapters.strava_adapter import MockStravaAdapter
from apex_coach.adapters.whoop_adapter import MockWhoopAdapter
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


@cli.command(name="whoop-smoke")
@click.option(
    "--date",
    default=None,
    help="ISO 8601 date to fetch (defaults to today, UTC).",
)
def whoop_smoke(date: str | None):
    """Fetch (mock) today's WHOOP daily payload (recovery, cycle, sleep) and print it. No network calls."""
    if date is None:
        date = datetime.now(timezone.utc).date().isoformat()

    adapter = MockWhoopAdapter()
    payload = adapter.get_daily_payload(date)

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


if __name__ == "__main__":
    cli()
