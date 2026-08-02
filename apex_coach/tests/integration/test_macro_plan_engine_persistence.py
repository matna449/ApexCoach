"""F20.3 (#142): preview_macro_plan()/accept_macro_plan() against a fixture
DB + real repos, mirroring run_monthly_review's own orchestrator-level
tests in test_monthly_engine_persistence.py. The pure generate_macro_plan()/
estimate_current_weekly_load_au() functions themselves are already fully
covered in test_macro_plan_engine.py (unit, no I/O) -- these tests exercise
the read/write orchestration around them: the activity-history read, the
already-set/don't-clobber guardrail, and the race_goals + monthly_targets
writes.
"""

import pytest

from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.plan_repository import PlanRepository
from apex_coach.db.schema import metadata
from apex_coach.engines.macro_plan_engine import accept_macro_plan, preview_macro_plan

TODAY = "2026-01-05"  # Monday
RACE_DATE = "2026-03-09"  # exactly 9 weeks out -- 5K's minimum block length


@pytest.fixture
def repos():
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    return PlanRepository(engine), MetricsRepository(engine)


def _seed_activity(metrics_repo, date, strava_id, load_score):
    metrics_repo.insert_daily_metrics(date=date)
    metrics_repo.save_activity(
        strava_id=strava_id,
        date=date,
        activity_type="Run",
        duration_seconds=3600,
        load_score=load_score,
    )


# -- preview_macro_plan -------------------------------------------------------


def test_preview_macro_plan_returns_the_full_proposal_and_writes_nothing(repos):
    plan_repo, metrics_repo = repos
    _seed_activity(metrics_repo, "2026-01-01", "s1", 100.0)

    preview = preview_macro_plan(plan_repo, metrics_repo, "5K", RACE_DATE, TODAY)

    assert preview["goal_distance"] == "5K"
    assert preview["race_date"] == RACE_DATE
    assert preview["weeks_to_race"] == 9
    assert preview["current_phase"] == "BASE"
    assert preview["current_weekly_load_au"] > 0
    assert [m["month_start_date"] for m in preview["months"]] == [
        "2026-01-01",
        "2026-02-01",
        "2026-03-01",
    ]
    assert all(m["already_set"] is False for m in preview["months"])

    # Writes nothing -- every recommended month is still unset afterward.
    for month in preview["months"]:
        assert plan_repo.get_monthly_target(month["month_start_date"]) is None
    assert plan_repo.get_active_race_goal() is None


def test_preview_macro_plan_flags_a_month_that_already_has_athlete_set_values(repos):
    plan_repo, metrics_repo = repos
    plan_repo.insert_monthly_target(
        month_start_date="2026-02-01", periodisation_phase="RECOVERY", load_target_total=50.0
    )

    preview = preview_macro_plan(plan_repo, metrics_repo, "5K", RACE_DATE, TODAY)

    by_month = {m["month_start_date"]: m for m in preview["months"]}
    assert by_month["2026-02-01"]["already_set"] is True
    assert by_month["2026-01-01"]["already_set"] is False
    assert by_month["2026-03-01"]["already_set"] is False


def test_preview_macro_plan_raises_when_not_enough_runway(repos):
    plan_repo, metrics_repo = repos
    with pytest.raises(ValueError):
        preview_macro_plan(plan_repo, metrics_repo, "MARATHON", "2026-01-26", TODAY)


# -- accept_macro_plan --------------------------------------------------------


def test_accept_macro_plan_writes_race_goal_and_seeds_every_month(repos):
    plan_repo, metrics_repo = repos
    _seed_activity(metrics_repo, "2026-01-01", "s1", 100.0)

    result = accept_macro_plan(plan_repo, metrics_repo, "5K", RACE_DATE, TODAY)

    goal = plan_repo.get_active_race_goal()
    assert goal["goal_distance"] == "5K"
    assert goal["target_race_date"] == RACE_DATE

    for month in result["months"]:
        assert month["written"] is True
        assert month["created"] is True
        row = plan_repo.get_monthly_target(month["month_start_date"])
        assert row["periodisation_phase"] == month["periodisation_phase"]
        assert row["load_target_total"] == month["load_target_total"]


def test_accept_macro_plan_does_not_clobber_an_already_customized_month(repos):
    plan_repo, metrics_repo = repos
    plan_repo.insert_monthly_target(
        month_start_date="2026-02-01", periodisation_phase="RECOVERY", load_target_total=50.0
    )

    result = accept_macro_plan(plan_repo, metrics_repo, "5K", RACE_DATE, TODAY)

    by_month = {m["month_start_date"]: m for m in result["months"]}
    assert by_month["2026-02-01"]["written"] is False

    # The athlete-set row is untouched -- not overwritten by the macro plan.
    row = plan_repo.get_monthly_target("2026-02-01")
    assert row["periodisation_phase"] == "RECOVERY"
    assert row["load_target_total"] == 50.0

    # The other two months, with no prior athlete-set values, were written.
    assert by_month["2026-01-01"]["written"] is True
    assert by_month["2026-03-01"]["written"] is True


def test_accept_macro_plan_rejects_a_second_active_goal_without_replace(repos):
    plan_repo, metrics_repo = repos
    accept_macro_plan(plan_repo, metrics_repo, "5K", RACE_DATE, TODAY)

    with pytest.raises(ValueError):
        accept_macro_plan(plan_repo, metrics_repo, "10K", "2026-04-01", TODAY)

    # Nothing from the rejected second call was written -- the original
    # goal is still active and unchanged.
    goal = plan_repo.get_active_race_goal()
    assert goal["goal_distance"] == "5K"


def test_accept_macro_plan_replace_abandons_old_goal_and_seeds_new_months(repos):
    plan_repo, metrics_repo = repos
    accept_macro_plan(plan_repo, metrics_repo, "5K", RACE_DATE, TODAY)

    result = accept_macro_plan(
        plan_repo, metrics_repo, "10K", "2026-04-13", TODAY, replace=True
    )

    goal = plan_repo.get_active_race_goal()
    assert goal["goal_distance"] == "10K"
    assert goal["target_race_date"] == "2026-04-13"

    # 10K's own recommended months are freshly written -- none of them
    # collide with what 5K already set (5K's plan only touched Jan/Feb/Mar,
    # 10K's longer block reaches into April).
    assert any(m["month_start_date"] == "2026-04-01" for m in result["months"])


def test_accept_macro_plan_raises_before_any_write_when_not_enough_runway(repos):
    plan_repo, metrics_repo = repos

    with pytest.raises(ValueError):
        accept_macro_plan(plan_repo, metrics_repo, "MARATHON", "2026-01-26", TODAY)

    assert plan_repo.get_active_race_goal() is None
    assert plan_repo.get_monthly_target("2026-01-01") is None
