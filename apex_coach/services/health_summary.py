"""The AI health agent's morning read (F21 spec §8). Pure: rows in, summary out.

Averages use prior days only, consistent with ADR-0021. Flags are computed on the
raw values, and rounding only keeps the response small.
"""

from datetime import date as _date
from datetime import datetime, time, timedelta

from apex_coach.services.hrv_trend import MIN_SAMPLE_DAYS, TRAILING_WINDOW_DAYS, compute_hrv_30d_avg

MIN_7D_SAMPLES = 3
RECOVERY_RED_BELOW = 34
LOW_RECOVERY_STREAK_DAYS = 3
SYNC_EXPECTED_BY = time(10, 0)
SYNC_STALE_AFTER = timedelta(hours=36)

_SUBJECTIVE_ANSWERS = {
    "rpe_yesterday": "rpe_yesterday",
    "soreness": "soreness_note",
    "soreness_level": "muscle_soreness",
    "sleep_quality": "sleep_quality_felt",
    "energy": "subjective_energy",
    "stress": "subjective_stress",
    "pain": "pain_note",
}

OK = "OK"
REAUTH_REQUIRED = "REAUTH_REQUIRED"
STALE = "STALE"


class _RowsAsRepository:
    """Lets compute_hrv_30d_avg run on rows already in memory, without one query per day."""

    def __init__(self, rows_by_date: dict[str, dict]):
        self._rows_by_date = rows_by_date

    def get_daily_metrics_range(self, start: str, end: str) -> list[dict]:
        return [row for day, row in self._rows_by_date.items() if start <= day <= end]


def rows_needed_from(today: _date, days: int) -> _date:
    """The earliest date the oldest day's 30-day average looks at."""
    return today - timedelta(days=days - 1 + TRAILING_WINDOW_DAYS)


def _round(value: float | None, digits: int | None = 1) -> float | int | None:
    return None if value is None else round(value, digits)


def _prior_values(rows_by_date: dict, day: _date, column: str, window: int) -> list[float]:
    prior = (rows_by_date.get((day - timedelta(days=n)).isoformat()) for n in range(1, window + 1))
    return [row[column] for row in prior if row is not None and row[column] is not None]


def _prior_avg(rows_by_date: dict, day: _date, column: str) -> float | None:
    values = _prior_values(rows_by_date, day, column, window=7)
    return sum(values) / len(values) if len(values) >= MIN_7D_SAMPLES else None


def _hrv_30d_avg(rows_by_date: dict, day: _date) -> float | None:
    avg, samples = compute_hrv_30d_avg(_RowsAsRepository(rows_by_date), day.isoformat())
    return avg if samples >= MIN_SAMPLE_DAYS else None


def _is_red(row: dict | None) -> bool:
    recovery = row["whoop_recovery_pct"] if row is not None else None
    return recovery is not None and recovery < RECOVERY_RED_BELOW


def _is_sync_stale(row: dict | None, day: _date, now: datetime) -> bool:
    if day != now.date() or now.time() < SYNC_EXPECTED_BY:
        return False
    return row is None or (row["whoop_recovery_pct"] is None and row["whoop_hrv_ms"] is None)


def _flags(rows_by_date: dict, row: dict | None, day: _date, hrv_7d: float | None, now) -> list[str]:
    flags = []
    if _is_red(row):
        flags.append("RECOVERY_RED")
    hrv = row["whoop_hrv_ms"] if row is not None else None
    # Multiplied out, so exactly -20 % does not flag through float rounding.
    if hrv is not None and hrv_7d is not None and 5 * hrv < 4 * hrv_7d:
        flags.append("HRV_BELOW_7D_20PCT")
    if all(
        _is_red(rows_by_date.get((day - timedelta(days=n)).isoformat()))
        for n in range(LOW_RECOVERY_STREAK_DAYS)
    ):
        flags.append("LOW_RECOVERY_3D")
    if _is_sync_stale(row, day, now):
        flags.append("SYNC_STALE")
    return flags


def _day_summary(rows_by_date: dict, day: _date, now: datetime) -> dict:
    row = rows_by_date.get(day.isoformat())
    values = row or {}
    hrv_7d = _prior_avg(rows_by_date, day, "whoop_hrv_ms")
    summary = {
        "date": day.isoformat(),
        "recovery_pct": _round(values.get("whoop_recovery_pct"), None),
        "hrv_ms": _round(values.get("whoop_hrv_ms")),
        "resting_hr_bpm": values.get("whoop_rhr_bpm"),
        "sleep_hours": _round(values.get("whoop_sleep_hours")),
        "sleep_performance_pct": _round(values.get("whoop_sleep_performance_pct"), None),
        "strain": _round(values.get("whoop_strain")),
        "hrv_7d_avg": _round(hrv_7d),
        "hrv_30d_avg": _round(_hrv_30d_avg(rows_by_date, day)),
        "rhr_7d_avg": _round(_prior_avg(rows_by_date, day, "whoop_rhr_bpm")),
        # Only what was answered, to keep the response small.
        "subjective": {
            answer: values[column]
            for answer, column in _SUBJECTIVE_ANSWERS.items()
            if values.get(column) is not None
        },
        "flags": _flags(rows_by_date, row, day, hrv_7d, now),
    }
    # Today's cycle runs until the next sleep. Omitted otherwise to keep the response small.
    if day == now.date() and summary["strain"] is not None:
        summary["strain_in_progress"] = True
    return summary


def _sync_summary(
    rows: list[dict], reauth_required: bool, pending_events: int, today_stale: bool, now: datetime
) -> dict:
    synced = [row["whoop_synced_at"] for row in rows if row["whoop_synced_at"] is not None]
    last_synced_at = max(synced, key=datetime.fromisoformat) if synced else None

    status = OK
    if reauth_required:
        status = REAUTH_REQUIRED
    elif (
        today_stale
        or last_synced_at is None
        or now - datetime.fromisoformat(last_synced_at) > SYNC_STALE_AFTER
    ):
        status = STALE
    return {"status": status, "last_synced_at": last_synced_at, "pending_events": pending_events}


def build_daily_health(
    rows: list[dict], days: int, reauth_required: bool, pending_events: int, now: datetime
) -> dict:
    """`rows` must reach back to rows_needed_from(). `now` is timezone-aware and local.
    Newest day first. Today always has an entry, other days only if they have a row."""
    rows_by_date = {row["date"]: row for row in rows}
    today = now.date()
    dates = [today - timedelta(days=n) for n in range(days)]
    summaries = [
        _day_summary(rows_by_date, day, now)
        for day in dates
        if day == today or day.isoformat() in rows_by_date
    ]
    today_stale = "SYNC_STALE" in summaries[0]["flags"]
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "sync": _sync_summary(rows, reauth_required, pending_events, today_stale, now),
        "days": summaries,
    }
