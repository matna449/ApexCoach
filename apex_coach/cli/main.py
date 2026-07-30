"""CLI entry point — command group. See docs/adr/0008."""

from datetime import datetime, timezone

import click

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


if __name__ == "__main__":
    cli()
