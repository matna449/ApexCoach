import pytest

from apex_coach.engines.monthly_engine import (
    build_month_summary,
    calculate_daily_target,
    calculate_weekly_target,
    flag_load_threshold,
    forecast_performance,
    hrv_trend_direction,
    load_overreach_detected,
    taper_adjusted_target,
)


# -- §5.1 Load Accumulation Model --------------------------------------------


def test_calculate_weekly_target():
    assert calculate_weekly_target(1200.0) == pytest.approx(1200.0 / 4.33)


def test_calculate_daily_target():
    weekly = calculate_weekly_target(1200.0)
    assert calculate_daily_target(weekly, 5) == pytest.approx(weekly / 5)


@pytest.mark.parametrize(
    "load_pct, expected",
    [(0.74, "LOAD_DEFICIT"), (0.75, None), (1.0, None), (1.15, None), (1.16, "OVERREACH_RISK")],
)
def test_flag_load_threshold_boundaries(load_pct, expected):
    assert flag_load_threshold(load_pct) == expected


# -- §5.2 Performance Forecast -------------------------------------------------


def test_hrv_trend_improving():
    assert hrv_trend_direction([70.0, 72.0, 75.0]) == "IMPROVING"


def test_hrv_trend_declining():
    assert hrv_trend_direction([75.0, 72.0, 70.0]) == "DECLINING"


def test_hrv_trend_stable():
    assert hrv_trend_direction([72.0, 72.0, 72.0]) == "STABLE"


def test_hrv_trend_stable_with_insufficient_data():
    assert hrv_trend_direction([72.0]) == "STABLE"
    assert hrv_trend_direction([]) == "STABLE"


@pytest.mark.parametrize(
    "load_projected_pct, hrv_trend, expected_status",
    [
        (0.95, "IMPROVING", "ON_TRACK"),
        (0.95, "STABLE", "ON_TRACK"),
        (0.95, "DECLINING", "AT_RISK"),
        (0.80, "STABLE", "MINOR_DEFICIT"),
        (0.60, "STABLE", "SIGNIFICANT_DEFICIT"),
    ],
)
def test_forecast_performance(load_projected_pct, hrv_trend, expected_status):
    status, message = forecast_performance(load_projected_pct, hrv_trend)
    assert status == expected_status
    assert status in message


def test_forecast_boundary_at_90_pct():
    status, _ = forecast_performance(0.90, "STABLE")
    assert status == "ON_TRACK"


def test_forecast_boundary_at_75_pct():
    status, _ = forecast_performance(0.75, "STABLE")
    assert status == "MINOR_DEFICIT"


@pytest.mark.parametrize(
    "weeks_to_race, expected_multiplier",
    [(None, 1.0), (4, 1.0), (3, 0.80), (2, 0.65), (1, 0.40), (0, 0.40)],
)
def test_taper_adjusted_target(weeks_to_race, expected_multiplier):
    result = taper_adjusted_target(1000.0, weeks_to_race)
    assert result == pytest.approx(1000.0 * expected_multiplier)


# -- Authority hierarchy (ADR-0002, ADR-0016) --------------------------------


def test_load_overreach_detected_true_for_3_consecutive_days():
    assert load_overreach_detected([1.20, 1.18, 1.20]) is True


def test_load_overreach_detected_false_if_any_of_last_3_days_not_overreached():
    assert load_overreach_detected([1.20, 1.10, 1.20]) is False


def test_load_overreach_detected_false_with_insufficient_history():
    assert load_overreach_detected([1.20, 1.20]) is False


def test_load_overreach_detected_only_looks_at_most_recent_3_days():
    # Overreach 5 days ago shouldn't matter if the last 3 aren't overreached.
    assert load_overreach_detected([1.20, 1.20, 1.20, 1.0, 1.0, 1.0]) is False


# -- §5.3 Monthly Summary ------------------------------------------------------


def test_build_month_summary_matches_worked_example_shape():
    session_scores = [
        {"execution_score": 91.2, "overpush_flag": False, "underpush_flag": False,
         "session_type": "Threshold", "date": "2026-06-17"},
        {"execution_score": 44.1, "overpush_flag": False, "underpush_flag": True,
         "session_type": "HIIT", "date": "2026-06-10"},
    ]

    summary = build_month_summary(
        month_label="June 2026",
        periodisation_phase="BUILD",
        load_target_au=1200.0,
        load_actual_au=1087.4,
        hrv_weekly_avgs_ms=[74.2, 71.8, 73.1, 72.4],
        session_scores=session_scores,
        sessions_skipped=3,
        sessions_written_off=1,
        recovery_weeks=0,
        weeks_to_race=None,
        days_elapsed=25,
        days_in_month=30,
    )

    assert summary["month"] == "June 2026"
    assert summary["load_target_au"] == 1200.0
    assert summary["load_actual_au"] == 1087.4
    assert summary["sessions_completed"] == 2
    assert summary["underpush_flags"] == 1
    assert summary["top_execution_session"]["execution_score"] == 91.2
    assert summary["worst_execution_session"]["execution_score"] == 44.1
    assert "load_status" in summary
    assert "key_observations" in summary
    assert "next_month_recommendation" in summary


def test_build_month_summary_handles_no_sessions():
    summary = build_month_summary(
        month_label="July 2026",
        periodisation_phase="RECOVERY",
        load_target_au=1000.0,
        load_actual_au=0.0,
        hrv_weekly_avgs_ms=[],
        session_scores=[],
        sessions_skipped=0,
        sessions_written_off=0,
        recovery_weeks=1,
        weeks_to_race=None,
        days_elapsed=1,
        days_in_month=31,
    )
    assert summary["sessions_completed"] == 0
    assert summary["top_execution_session"] is None
    assert summary["worst_execution_session"] is None
    assert summary["session_quality_avg"] == 0.0
