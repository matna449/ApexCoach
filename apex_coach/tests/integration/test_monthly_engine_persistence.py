import json

import pytest

from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.plan_repository import PlanRepository
from apex_coach.db.schema import metadata
from apex_coach.engines.monthly_engine import load_overreach_detected, run_monthly_review
from apex_coach.engines.weekly_engine import run_weekly_adaptation

MONTH_START = "2026-08-01"


@pytest.fixture
def repos():
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    return PlanRepository(engine), MetricsRepository(engine)


def _seed_activity_with_score(metrics_repo, date, strava_id, execution_score, overpush=False):
    metrics_repo.insert_daily_metrics(date=date)
    metrics_repo.save_activity(
        strava_id=strava_id,
        date=date,
        activity_type="Run",
        intended_session_type="Threshold",
        duration_seconds=3600,
        avg_hr_bpm=165,
        distance_metres=10000,
        elevation_gain_m=100,
    )
    activity_id = metrics_repo.get_activity(strava_id)["id"]
    metrics_repo.insert_session_score(
        activity_id=activity_id,
        execution_score=execution_score,
        overpush_flag=overpush,
        underpush_flag=False,
    )


def test_run_monthly_review_simulates_a_full_training_block(repos):
    plan_repo, metrics_repo = repos
    plan_repo.insert_monthly_target(
        month_start_date=MONTH_START,
        periodisation_phase="BUILD",
        load_target_total=1000.0,
    )

    # A handful of sessions spread across the month.
    _seed_activity_with_score(metrics_repo, "2026-08-03", "s1", 91.2, overpush=True)
    _seed_activity_with_score(metrics_repo, "2026-08-10", "s2", 70.0)
    _seed_activity_with_score(metrics_repo, "2026-08-17", "s3", 44.1, overpush=True)

    # HRV history across the weeks.
    for d, hrv in [("2026-08-04", 74.0), ("2026-08-11", 72.0), ("2026-08-18", 73.0)]:
        metrics_repo.upsert_daily_metrics(d, whoop_hrv_ms=hrv)

    # A recovery week and a skipped session somewhere in the month.
    plan_repo.insert_weekly_plan(
        week_start_date="2026-08-03",
        planned_sessions_json=json.dumps([{"day": "Monday", "session_type": "HIIT"}]),
        skipped_sessions=json.dumps(
            [{"session_type": "HIIT", "disposition": "written_off", "original_day": "Monday"}]
        ),
        week_status="ON_TRACK",
    )
    plan_repo.insert_weekly_plan(
        week_start_date="2026-08-10",
        planned_sessions_json="[]",
        week_status="RECOVERY_WEEK",
    )

    summary = run_monthly_review(plan_repo, metrics_repo, MONTH_START, today="2026-08-25")

    assert summary["sessions_completed"] == 3
    assert summary["overpush_flags"] == 2
    assert summary["sessions_written_off"] == 1
    assert summary["recovery_weeks"] == 1
    assert summary["load_actual_au"] > 0
    assert len(summary["hrv_weekly_avgs_ms"]) >= 1
    assert summary["load_status"] in (
        "ON_TRACK", "AT_RISK", "MINOR_DEFICIT", "SIGNIFICANT_DEFICIT"
    )

    row = plan_repo.get_monthly_target(MONTH_START)
    stored_summary = json.loads(row["month_summary_json"])
    assert stored_summary == summary
    assert row["load_actual_total"] == summary["load_actual_au"]


def test_run_monthly_review_raises_for_unknown_month(repos):
    plan_repo, metrics_repo = repos
    with pytest.raises(ValueError):
        run_monthly_review(plan_repo, metrics_repo, "2099-01-01", today="2099-01-15")


# -- Authority hierarchy (ADR-0002): weekly_engine cannot override a --------
# -- monthly-triggered constraint --------------------------------------------


def test_weekly_engine_cannot_override_monthly_overreach_trigger(repos):
    plan_repo, metrics_repo = repos

    # A week that would otherwise have every reason to stay ON_TRACK: no
    # skipped sessions, no RED days, load comfortably on target.
    plan_repo.insert_weekly_plan(
        week_start_date="2026-08-03",
        planned_sessions_json=json.dumps([{"day": "Monday", "session_type": "HIIT"}]),
        week_status="ON_TRACK",
        load_target=280.0,
        load_actual=280.0,
    )
    plan_repo.insert_monthly_target(
        month_start_date=MONTH_START, load_actual_total=280.0, load_target_total=280.0
    )

    # Monthly engine detects 3 consecutive days of overreach — the
    # authority-hierarchy signal.
    assert load_overreach_detected([1.20, 1.18, 1.20]) is True

    result = run_weekly_adaptation(
        plan_repo,
        metrics_repo,
        "2026-08-03",
        today="2026-08-04",
        monthly_overreach_detected=True,
    )

    # Monthly's trigger forces RECOVERY_WEEK even though nothing at the
    # weekly level would have caused it on its own.
    assert result["week_status"] == "RECOVERY_WEEK"


def test_weekly_engine_stays_on_track_without_monthly_trigger(repos):
    plan_repo, metrics_repo = repos
    plan_repo.insert_weekly_plan(
        week_start_date="2026-08-03",
        planned_sessions_json=json.dumps([{"day": "Monday", "session_type": "HIIT"}]),
        week_status="ON_TRACK",
        load_target=280.0,
        load_actual=280.0,
    )
    plan_repo.insert_monthly_target(
        month_start_date=MONTH_START, load_actual_total=280.0, load_target_total=280.0
    )

    result = run_weekly_adaptation(
        plan_repo,
        metrics_repo,
        "2026-08-03",
        today="2026-08-04",
        monthly_overreach_detected=False,
    )

    assert result["week_status"] == "ON_TRACK"
