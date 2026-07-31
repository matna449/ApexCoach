import json

import pytest

from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.plan_repository import PlanRepository
from apex_coach.db.schema import metadata
from apex_coach.engines.weekly_engine import run_weekly_adaptation

WEEK_START = "2026-08-03"  # a Monday


@pytest.fixture
def repos():
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    return PlanRepository(engine), MetricsRepository(engine)


def _seed_week(plan_repo, planned_sessions, week_status="ON_TRACK"):
    plan_repo.insert_weekly_plan(
        week_start_date=WEEK_START,
        planned_sessions_json=json.dumps(planned_sessions),
        week_status=week_status,
        load_target=280.0,
        load_actual=0.0,
    )


def _seed_month(plan_repo, load_actual_total, load_target_total=280.0):
    plan_repo.insert_monthly_target(
        month_start_date="2026-08-01",
        load_actual_total=load_actual_total,
        load_target_total=load_target_total,
    )


def test_no_trigger_leaves_week_on_track_with_no_diff(repos):
    plan_repo, metrics_repo = repos
    planned = [{"day": "Monday", "session_type": "HIIT"}]
    _seed_week(plan_repo, planned)
    _seed_month(plan_repo, load_actual_total=200.0)

    result = run_weekly_adaptation(
        plan_repo, metrics_repo, WEEK_START, today="2026-08-04"
    )

    assert result["week_status"] == "ON_TRACK"
    assert result["diff"] == []

    row = plan_repo.get_weekly_plan(WEEK_START)
    assert row["week_status"] == "ON_TRACK"


def test_skipped_key_session_with_load_deficit_reschedules_and_transitions(repos):
    plan_repo, metrics_repo = repos
    planned = [
        {"day": "Monday", "session_type": "HIIT"},
        {"day": "Thursday", "session_type": "Zone2_Long"},
    ]
    _seed_week(plan_repo, planned)
    _seed_month(plan_repo, load_actual_total=100.0)  # 100/280 = 35.7% -- well under 80%

    result = run_weekly_adaptation(
        plan_repo,
        metrics_repo,
        WEEK_START,
        today="2026-08-04",  # Tuesday -- 5 days remaining
        key_session_skipped_type="HIIT",
        key_session_skipped_day="Monday",
    )

    assert result["week_status"] == "LOAD_DEFICIT"
    assert len(result["skipped_sessions"]) == 1
    assert result["skipped_sessions"][0]["disposition"] == "rescheduled"
    assert result["diff"]  # something changed

    row = plan_repo.get_weekly_plan(WEEK_START)
    assert row["week_status"] == "LOAD_DEFICIT"
    stored_skipped = json.loads(row["skipped_sessions"])
    assert stored_skipped[0]["session_type"] == "HIIT"


def test_two_consecutive_red_days_triggers_recovery_week_and_replaces_plan(repos):
    plan_repo, metrics_repo = repos
    planned = [
        {"day": "Monday", "session_type": "HIIT"},
        {"day": "Wednesday", "session_type": "Threshold"},
    ]
    _seed_week(plan_repo, planned)
    _seed_month(plan_repo, load_actual_total=200.0)

    today = "2026-08-05"  # Wednesday
    metrics_repo.insert_daily_metrics(date="2026-08-03", whoop_recovery_pct=20.0)
    metrics_repo.insert_daily_metrics(date="2026-08-04", whoop_recovery_pct=15.0)

    result = run_weekly_adaptation(plan_repo, metrics_repo, WEEK_START, today=today)

    assert result["week_status"] == "RECOVERY_WEEK"
    by_day = {s["day"]: s["session_type"] for s in result["adapted_sessions"]}
    assert by_day["Monday"] == "Zone2_Short"
    assert by_day["Wednesday"] == "Zone2_Short"


def test_end_of_week_transitions_to_complete_regardless_of_state(repos):
    plan_repo, metrics_repo = repos
    _seed_week(plan_repo, [{"day": "Monday", "session_type": "HIIT"}])
    _seed_month(plan_repo, load_actual_total=200.0)

    result = run_weekly_adaptation(
        plan_repo, metrics_repo, WEEK_START, today="2026-08-09", end_of_week_reached=True
    )

    assert result["week_status"] == "COMPLETE"


def test_raises_for_unknown_week(repos):
    plan_repo, metrics_repo = repos
    with pytest.raises(ValueError):
        run_weekly_adaptation(plan_repo, metrics_repo, "2099-01-05", today="2099-01-06")


def test_null_week_status_on_freshly_planned_week_defaults_to_on_track(repos):
    """A week just written by `plan-week` (F11.1) has week_status=NULL —
    no evaluation has run yet. Surfaced by real usage (F11.9): this must
    not crash decide_state_transition, which only accepts WEEK_STATUSES."""
    plan_repo, metrics_repo = repos
    plan_repo.insert_weekly_plan(
        week_start_date=WEEK_START,
        planned_sessions_json=json.dumps([{"day": "Monday", "session_type": "HIIT"}]),
    )

    result = run_weekly_adaptation(plan_repo, metrics_repo, WEEK_START, today="2026-08-04")

    assert result["week_status"] == "ON_TRACK"
    assert plan_repo.get_weekly_plan(WEEK_START)["week_status"] == "ON_TRACK"


def test_null_load_actual_total_treated_as_zero_not_a_crash(repos):
    """monthly_targets.load_actual_total is legitimately NULL until
    run_monthly_review() (F11.10) has run at least once. Surfaced by real
    usage (F11.9): dividing None by load_target_total must not crash."""
    plan_repo, metrics_repo = repos
    planned = [{"day": "Monday", "session_type": "HIIT"}]
    _seed_week(plan_repo, planned)
    plan_repo.insert_monthly_target(month_start_date="2026-08-01", load_target_total=280.0)

    result = run_weekly_adaptation(
        plan_repo,
        metrics_repo,
        WEEK_START,
        today="2026-08-04",
        key_session_skipped_type="HIIT",
        key_session_skipped_day="Monday",
    )

    # 0 (unset) actual / 280 target = 0% -- well under 80%, same as the
    # already-tested explicit-100.0 LOAD_DEFICIT case above.
    assert result["week_status"] == "LOAD_DEFICIT"
