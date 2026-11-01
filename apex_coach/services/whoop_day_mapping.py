"""Which local date a WHOOP record belongs to (F21 spec §7). Pure functions."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Cycles start at sleep onset, often before midnight. This pushes a 22:30 start
# onto the day it mostly covers.
CYCLE_DAY_OFFSET = timedelta(hours=6)


def local_date(timestamp: str, tz: ZoneInfo) -> str:
    return datetime.fromisoformat(timestamp).astimezone(tz).date().isoformat()


def sleep_date(sleep: dict, tz: ZoneInfo) -> str:
    """Recovery inherits this date from its sleep."""
    return local_date(sleep["end"], tz)


def cycle_date(cycle: dict, tz: ZoneInfo) -> str:
    start = datetime.fromisoformat(cycle["start"]) + CYCLE_DAY_OFFSET
    return start.astimezone(tz).date().isoformat()


def is_cycle_in_progress(cycle: dict) -> bool:
    return cycle.get("end") is None


def sleep_duration(sleep: dict) -> timedelta:
    return datetime.fromisoformat(sleep["end"]) - datetime.fromisoformat(sleep["start"])
