"""30-day rolling HRV baseline for classify_daily_inputs (ADR-0013, ADR-0021).

ADR-0013 deferred this computation entirely: classify_daily_inputs() takes
hrv_30d_avg_ms as a plain parameter and stays pure. This module is the
"separate, not-yet-built concern" it pointed at — it reads daily_metrics
and produces the number that parameter expects.

Two decisions ADR-0013 explicitly left open, both resolved here and
recorded in ADR-0021:

1. Whether today's own reading counts toward its own baseline — no. The
   window for date D is the 30 calendar days strictly before D,
   [D-30, D-1]. Including D would compare today's HRV against a baseline
   that partly *is* today's HRV, biasing the average toward whatever
   today happens to be and muting the very delta the baseline exists to
   surface.

2. What happens with fewer than 30 days of history — average over
   however many valid readings exist, but only trust that average once
   there are at least MIN_SAMPLE_DAYS of them. Below that threshold,
   resolve_hrv_30d_avg_for_classification() returns the day's own HRV
   reading as its "baseline", forcing hrv_delta_ms to exactly 0 inside
   classify_daily_inputs — which classify_hrv_delta() bands as NEUTRAL
   per its inclusive -5..+5 range (docs/adr/0013). That's an explicit
   no-signal outcome, not a spurious POSITIVE/NEGATIVE/STRONG_NEG read
   manufactured from one or two noisy days. It requires no change to
   classify_daily_inputs's signature.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta

from apex_coach.db.metrics_repository import MetricsRepository

TRAILING_WINDOW_DAYS = 30
MIN_SAMPLE_DAYS = 7


def compute_hrv_30d_avg(
    repo: MetricsRepository, date: str
) -> tuple[float | None, int]:
    """Average whoop_hrv_ms over the 30 days strictly before `date`.

    Reads whatever daily_metrics rows actually exist in that window —
    there may be fewer than 30 (early in the app's life) — and skips rows
    where whoop_hrv_ms is None (a health-check-only day per ADR-0012's
    upsert model carries no WHOOP reading). Averages over however many
    valid readings remain.

    Returns (None, 0) when the window contains no valid HRV reading at
    all — e.g. the first-ever run, where no prior daily_metrics rows
    exist yet.
    """
    end = _date.fromisoformat(date) - timedelta(days=1)
    start = end - timedelta(days=TRAILING_WINDOW_DAYS - 1)

    rows = repo.get_daily_metrics_range(start.isoformat(), end.isoformat())
    values = [row["whoop_hrv_ms"] for row in rows if row["whoop_hrv_ms"] is not None]

    if not values:
        return None, 0
    return sum(values) / len(values), len(values)


def resolve_hrv_30d_avg_for_classification(
    repo: MetricsRepository,
    date: str,
    current_hrv_ms: float,
    min_sample_days: int = MIN_SAMPLE_DAYS,
) -> float:
    """The hrv_30d_avg_ms value to feed classify_daily_inputs() for `date`.

    Cold-start policy (ADR-0021): fewer than `min_sample_days` valid
    readings in the trailing window means the average is too noisy to
    treat as a real baseline, so we fall back to `current_hrv_ms` —
    forcing hrv_delta_ms == 0 and an HRV_NEUTRAL band — instead of
    classifying a delta computed against a 1-, 2-, or 6-day "average".
    """
    avg, sample_count = compute_hrv_30d_avg(repo, date)
    if sample_count < min_sample_days:
        return current_hrv_ms
    return avg
