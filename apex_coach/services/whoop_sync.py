"""Turns WHOOP webhook events into daily_metrics rows (F21 spec §6).

Never sleeps: a record that is not scored yet is left for the next webhook or
the daily reconcile. score_state is read from the raw dict, because the Pydantic
models reject anything but SCORED and the CLI relies on that (finding #12).
"""

import base64
import hashlib
import hmac
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apex_coach.adapters.whoop_adapter import RealWhoopAdapter
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.webhook_repository import IGNORED, PENDING, PROCESSED
from apex_coach.services.whoop_day_mapping import cycle_date, sleep_date, sleep_duration

# WHOOP's docs give no window. Our choice, see F21 spec §6.
SIGNATURE_TOLERANCE_MS = 5 * 60 * 1000
STRAIN_LOOKBACK = timedelta(hours=48)
RECONCILE_DEFAULT_DAYS = 3
RECONCILE_MAX_DAYS = 30

SCORED = "SCORED"
PENDING_SCORE = "PENDING_SCORE"

_SLEEP_COLUMNS = {
    "whoop_sleep_hours": None,
    "whoop_sleep_performance_pct": None,
    "whoop_sleep_id": None,
}
_RECOVERY_COLUMNS = {
    "whoop_recovery_pct": None,
    "whoop_hrv_ms": None,
    "whoop_rhr_bpm": None,
    "whoop_recovery_score_state": None,
}


def is_valid_signature(
    secret: str, timestamp: str | None, body: bytes, signature: str | None, now_ms: int
) -> bool:
    if not timestamp or not signature:
        return False
    try:
        if abs(now_ms - int(timestamp)) > SIGNATURE_TOLERANCE_MS:
            return False
    except ValueError:
        return False
    digest = hmac.new(secret.encode(), timestamp.encode() + body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest), signature.encode())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sleep_fields(sleep: dict) -> dict:
    fields = {**_SLEEP_COLUMNS, "whoop_sleep_id": sleep["id"]}
    if sleep["score_state"] == SCORED:
        stages = sleep["score"]["stage_summary"]
        asleep_milli = stages["total_in_bed_time_milli"] - stages["total_awake_time_milli"]
        fields["whoop_sleep_hours"] = asleep_milli / 1000 / 60 / 60
        fields["whoop_sleep_performance_pct"] = sleep["score"]["sleep_performance_percentage"]
    return fields


def _recovery_fields(recovery: dict) -> dict:
    fields = {
        **_RECOVERY_COLUMNS,
        "whoop_recovery_score_state": recovery["score_state"],
        "whoop_cycle_id": str(recovery["cycle_id"]),
    }
    if recovery["score_state"] == SCORED:
        score = recovery["score"]
        fields["whoop_recovery_pct"] = score["recovery_score"]
        fields["whoop_hrv_ms"] = score["hrv_rmssd_milli"]
        # The column is an Integer and WHOOP sends a float (finding #8).
        fields["whoop_rhr_bpm"] = round(score["resting_heart_rate"])
    return fields


def _is_shorter_than_stored_sleep(sleep: dict, date: str, whoop, metrics) -> bool:
    """Two main sleeps on one local date: the longest wins (F21 spec §7)."""
    row = metrics.get_daily_metrics(date)
    if row is None or row["whoop_sleep_id"] in (None, sleep["id"]):
        return False
    stored = whoop.get_sleep(row["whoop_sleep_id"])
    return stored is not None and sleep_duration(stored) > sleep_duration(sleep)


def _sync_sleep(sleep_id: str, whoop, metrics, tz: ZoneInfo, now_fn) -> str:
    sleep = whoop.get_sleep(sleep_id)
    if sleep is None or sleep.get("end") is None:
        return PENDING
    if sleep.get("nap"):
        return IGNORED
    if sleep["score_state"] == PENDING_SCORE:
        return PENDING

    date = sleep_date(sleep, tz)
    if _is_shorter_than_stored_sleep(sleep, date, whoop, metrics):
        return IGNORED

    synced = {"whoop_synced_at": now_fn().isoformat()}
    metrics.upsert_daily_metrics(date, **_sleep_fields(sleep), **synced)

    recovery = whoop.get_recovery_for_cycle(sleep["cycle_id"])
    status = PROCESSED
    if recovery is None or recovery["score_state"] == PENDING_SCORE:
        status = PENDING
    else:
        metrics.upsert_daily_metrics(date, **_recovery_fields(recovery), **synced)

    # WHOOP has no cycle webhook, so strain comes along with sleep and recovery.
    _sync_strain(whoop.get_cycles((now_fn() - STRAIN_LOOKBACK).isoformat()), metrics, tz, synced)
    return status


def _clear_sleep(sleep_id: str, metrics, now_fn) -> str:
    """Keeps the row, because subjective answers may live on it."""
    row = metrics.get_daily_metrics_by_whoop_sleep_id(sleep_id)
    if row is not None:
        metrics.upsert_daily_metrics(
            row["date"],
            **_SLEEP_COLUMNS,
            **_RECOVERY_COLUMNS,
            whoop_synced_at=now_fn().isoformat(),
        )
    return PROCESSED


def process_event(
    event_type: str,
    record_id: str,
    whoop: RealWhoopAdapter,
    metrics: MetricsRepository,
    tz: ZoneInfo,
    now_fn: Callable[[], datetime] = _now,
) -> str:
    """Returns the event's status. Writes are upserts by date, so a replay is safe."""
    if event_type in ("sleep.updated", "recovery.updated"):
        return _sync_sleep(record_id, whoop, metrics, tz, now_fn)
    if event_type in ("sleep.deleted", "recovery.deleted"):
        return _clear_sleep(record_id, metrics, now_fn)
    return IGNORED


def _sync_strain(cycles: list[dict], metrics, tz: ZoneInfo, synced: dict) -> None:
    for cycle in cycles:
        if cycle["score_state"] == PENDING_SCORE:
            continue
        strain = cycle["score"]["strain"] if cycle["score_state"] == SCORED else None
        metrics.upsert_daily_metrics(cycle_date(cycle, tz), whoop_strain=strain, **synced)


def reconcile(
    whoop: RealWhoopAdapter,
    metrics: MetricsRepository,
    tz: ZoneInfo,
    days: int = RECONCILE_DEFAULT_DAYS,
    now_fn: Callable[[], datetime] = _now,
) -> dict[str, int]:
    """Re-fetches the last local days by range, so a missed webhook costs nothing."""
    now = now_fn()
    today = now.astimezone(tz).date()
    first_day = (today - timedelta(days=days - 1)).isoformat()
    # A sleep ending on the first day started the evening before, and a cycle's
    # date can be the day after its start.
    start = (
        datetime.combine(today - timedelta(days=days), datetime.min.time(), tzinfo=tz)
        .astimezone(timezone.utc)
        .isoformat()
    )
    synced = {"whoop_synced_at": now.isoformat()}

    main_sleeps: dict[str, dict] = {}
    for sleep in whoop.get_sleeps(start):
        if sleep.get("nap") or sleep.get("end") is None or sleep["score_state"] == PENDING_SCORE:
            continue
        date = sleep_date(sleep, tz)
        if date >= first_day and (
            date not in main_sleeps or sleep_duration(sleep) > sleep_duration(main_sleeps[date])
        ):
            main_sleeps[date] = sleep

    recoveries = {r["sleep_id"]: r for r in whoop.get_recoveries(start)}
    counts = {"sleeps": 0, "recoveries": 0, "cycles": 0}
    for date, sleep in main_sleeps.items():
        metrics.upsert_daily_metrics(date, **_sleep_fields(sleep), **synced)
        counts["sleeps"] += 1
        recovery = recoveries.get(sleep["id"])
        if recovery is not None and recovery["score_state"] != PENDING_SCORE:
            metrics.upsert_daily_metrics(date, **_recovery_fields(recovery), **synced)
            counts["recoveries"] += 1

    cycles = [c for c in whoop.get_cycles(start) if cycle_date(c, tz) >= first_day]
    _sync_strain(cycles, metrics, tz, synced)
    counts["cycles"] = len(cycles)
    return counts
