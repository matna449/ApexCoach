from datetime import date, timedelta

import pytest

from apex_coach.adapters.whoop_adapter import MockWhoopAdapter
from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.schema import metadata
from apex_coach.orchestrator.orchestrator import (
    HRVDeltaBand,
    classify_daily_inputs,
)
from apex_coach.services.hrv_trend import (
    MIN_SAMPLE_DAYS,
    compute_hrv_30d_avg,
    resolve_hrv_30d_avg_for_classification,
)

TARGET_DATE = "2026-07-31"


@pytest.fixture
def repo():
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    return MetricsRepository(engine)


def _days_before(target: str, n: int) -> str:
    return (date.fromisoformat(target) - timedelta(days=n)).isoformat()


# -- compute_hrv_30d_avg — reads whatever's actually there -------------------


def test_full_30_days_of_history_averages_all_of_them(repo):
    # 30 days strictly before TARGET_DATE, each with a distinct hrv value.
    for n in range(1, 31):
        repo.insert_daily_metrics(
            date=_days_before(TARGET_DATE, n), whoop_hrv_ms=float(n)
        )

    avg, count = compute_hrv_30d_avg(repo, TARGET_DATE)

    assert count == 30
    assert avg == pytest.approx(sum(range(1, 31)) / 30)


def test_partial_history_averages_only_the_days_present(repo):
    for n in range(1, 6):  # 5 days of history
        repo.insert_daily_metrics(
            date=_days_before(TARGET_DATE, n), whoop_hrv_ms=float(10 * n)
        )

    avg, count = compute_hrv_30d_avg(repo, TARGET_DATE)

    assert count == 5
    assert avg == pytest.approx((10 + 20 + 30 + 40 + 50) / 5)


def test_zero_history_returns_none_and_zero_count(repo):
    avg, count = compute_hrv_30d_avg(repo, TARGET_DATE)

    assert avg is None
    assert count == 0


def test_rows_with_no_whoop_hrv_ms_are_skipped(repo):
    repo.insert_daily_metrics(date=_days_before(TARGET_DATE, 1), whoop_hrv_ms=60.0)
    # health-check-only day: no WHOOP fetch that day (ADR-0012)
    repo.insert_daily_metrics(date=_days_before(TARGET_DATE, 2), muscle_soreness=3)
    repo.insert_daily_metrics(date=_days_before(TARGET_DATE, 3), whoop_hrv_ms=80.0)

    avg, count = compute_hrv_30d_avg(repo, TARGET_DATE)

    assert count == 2
    assert avg == pytest.approx(70.0)


def test_window_excludes_the_target_date_itself(repo):
    repo.insert_daily_metrics(date=_days_before(TARGET_DATE, 1), whoop_hrv_ms=60.0)
    # Target date's own row already exists (WHOOP fetch happened this morning)
    # with an extreme value that must not leak into its own baseline.
    repo.insert_daily_metrics(date=TARGET_DATE, whoop_hrv_ms=999.0)

    avg, count = compute_hrv_30d_avg(repo, TARGET_DATE)

    assert count == 1
    assert avg == pytest.approx(60.0)


def test_window_excludes_days_older_than_30(repo):
    repo.insert_daily_metrics(date=_days_before(TARGET_DATE, 1), whoop_hrv_ms=60.0)
    repo.insert_daily_metrics(date=_days_before(TARGET_DATE, 31), whoop_hrv_ms=1000.0)

    avg, count = compute_hrv_30d_avg(repo, TARGET_DATE)

    assert count == 1
    assert avg == pytest.approx(60.0)


# -- resolve_hrv_30d_avg_for_classification — cold-start policy (ADR-0021) --


def test_resolve_uses_real_average_when_at_or_above_min_sample_days(repo):
    for n in range(1, MIN_SAMPLE_DAYS + 1):
        repo.insert_daily_metrics(
            date=_days_before(TARGET_DATE, n), whoop_hrv_ms=70.0
        )

    result = resolve_hrv_30d_avg_for_classification(
        repo, TARGET_DATE, current_hrv_ms=50.0
    )

    assert result == pytest.approx(70.0)


def test_resolve_falls_back_to_current_hrv_below_min_sample_days(repo):
    for n in range(1, MIN_SAMPLE_DAYS):  # one short of the threshold
        repo.insert_daily_metrics(
            date=_days_before(TARGET_DATE, n), whoop_hrv_ms=70.0
        )

    result = resolve_hrv_30d_avg_for_classification(
        repo, TARGET_DATE, current_hrv_ms=50.0
    )

    assert result == 50.0


def test_resolve_falls_back_to_current_hrv_on_zero_history(repo):
    result = resolve_hrv_30d_avg_for_classification(
        repo, TARGET_DATE, current_hrv_ms=50.0
    )

    assert result == 50.0


def test_resolve_respects_custom_min_sample_days(repo):
    for n in range(1, 3):  # 2 days of history
        repo.insert_daily_metrics(
            date=_days_before(TARGET_DATE, n), whoop_hrv_ms=70.0
        )

    result = resolve_hrv_30d_avg_for_classification(
        repo, TARGET_DATE, current_hrv_ms=50.0, min_sample_days=2
    )

    assert result == pytest.approx(70.0)


# -- wired into classify_daily_inputs — cold start yields NEUTRAL, not a --
# -- spurious band, and requires no change to classify_daily_inputs itself --


def test_cold_start_produces_neutral_band_without_touching_classify_daily_inputs(
    repo,
):
    # Only 2 days of history — below MIN_SAMPLE_DAYS — with an average far
    # from today's reading. If this leaked through as a real baseline it
    # would classify as STRONG_NEG; the cold-start policy must prevent that.
    for n in range(1, 3):
        repo.insert_daily_metrics(
            date=_days_before(TARGET_DATE, n), whoop_hrv_ms=200.0
        )

    payload = MockWhoopAdapter().get_daily_payload(TARGET_DATE)
    hrv_30d_avg_ms = resolve_hrv_30d_avg_for_classification(
        repo, TARGET_DATE, current_hrv_ms=payload.whoop_hrv_ms
    )

    result = classify_daily_inputs(
        payload, muscle_soreness=3, hrv_30d_avg_ms=hrv_30d_avg_ms
    )

    assert result["hrv_delta_ms"] == 0.0
    assert result["hrv_delta_band"] == HRVDeltaBand.NEUTRAL
