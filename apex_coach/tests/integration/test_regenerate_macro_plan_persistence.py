"""F20.4 (#143): regenerate_macro_plan() against a fixture DB + real repos,
mirroring test_macro_plan_engine_persistence.py's own structure. Covers the
behavior specific to regenerate (future-months-only, still respecting the
already-customized-month guardrail, and the stale-week-structure warning)
-- preview/accept's own behavior is already covered there.
"""

import json

import pytest

from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.plan_repository import PlanRepository
from apex_coach.db.schema import metadata
from apex_coach.engines.macro_plan_engine import accept_macro_plan, regenerate_macro_plan

TODAY = "2026-01-05"  # Monday
INITIAL_RACE_DATE = "2026-03-09"  # 5K's exact 9-week minimum from TODAY
NEW_RACE_DATE = "2026-05-04"  # 10K, 17 weeks out from TODAY


@pytest.fixture
def repos():
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    return PlanRepository(engine), MetricsRepository(engine)


def test_regenerate_macro_plan_raises_without_an_active_goal(repos):
    plan_repo, metrics_repo = repos
    with pytest.raises(ValueError):
        regenerate_macro_plan(plan_repo, metrics_repo, "10K", NEW_RACE_DATE, TODAY)


def test_regenerate_macro_plan_leaves_the_current_month_untouched(repos):
    plan_repo, metrics_repo = repos
    accept_macro_plan(plan_repo, metrics_repo, "5K", INITIAL_RACE_DATE, TODAY)
    original_january = plan_repo.get_monthly_target("2026-01-01")

    result = regenerate_macro_plan(plan_repo, metrics_repo, "10K", NEW_RACE_DATE, TODAY)

    # January (today's month) never appears in the regenerated output at all.
    assert all(m["month_start_date"] != "2026-01-01" for m in result["months"])

    # ...and its stored row is byte-for-byte what the original 5K accept wrote.
    january_after = plan_repo.get_monthly_target("2026-01-01")
    assert january_after["periodisation_phase"] == original_january["periodisation_phase"]
    assert january_after["load_target_total"] == original_january["load_target_total"]


def test_regenerate_macro_plan_updates_the_race_goal_and_writes_future_months(repos):
    plan_repo, metrics_repo = repos
    accept_macro_plan(plan_repo, metrics_repo, "5K", INITIAL_RACE_DATE, TODAY)

    result = regenerate_macro_plan(plan_repo, metrics_repo, "10K", NEW_RACE_DATE, TODAY)

    goal = plan_repo.get_active_race_goal()
    assert goal["goal_distance"] == "10K"
    assert goal["target_race_date"] == NEW_RACE_DATE

    # The new block reaches further out than the original 5K one did (May
    # vs. March) -- confirms the future months actually reflect the new
    # template, not a stale copy of the old one.
    assert any(m["month_start_date"] == "2026-05-01" for m in result["months"])
    for month in result["months"]:
        assert month["written"] is True
        row = plan_repo.get_monthly_target(month["month_start_date"])
        assert row["periodisation_phase"] == month["periodisation_phase"]
        assert row["load_target_total"] == month["load_target_total"]


def test_regenerate_macro_plan_still_respects_the_already_customized_guardrail(repos):
    plan_repo, metrics_repo = repos
    accept_macro_plan(plan_repo, metrics_repo, "5K", INITIAL_RACE_DATE, TODAY)

    # Athlete hand-edits March after the original accept -- via
    # upsert_monthly_target's default source='ATHLETE', the same path
    # set-monthly-target/the web UI use, not a raw repository call that
    # would leave source at whatever accept_macro_plan() originally wrote.
    plan_repo.upsert_monthly_target("2026-03-01", "RECOVERY", 25.0)

    result = regenerate_macro_plan(plan_repo, metrics_repo, "10K", NEW_RACE_DATE, TODAY)

    by_month = {m["month_start_date"]: m for m in result["months"]}
    assert by_month["2026-03-01"]["written"] is False
    assert by_month["2026-03-01"]["stale_week_structure"] is False

    row = plan_repo.get_monthly_target("2026-03-01")
    assert row["periodisation_phase"] == "RECOVERY"
    assert row["load_target_total"] == 25.0

    # Other future months, not hand-edited, were still regenerated.
    assert by_month["2026-02-01"]["written"] is True


def test_regenerate_macro_plan_flags_stale_week_structure(repos):
    plan_repo, metrics_repo = repos
    accept_macro_plan(plan_repo, metrics_repo, "5K", INITIAL_RACE_DATE, TODAY)

    # February already has a generated (and pushed) week structure from
    # the original 5K block.
    plan_repo.insert_weekly_plan(
        week_start_date="2026-02-02",
        planned_sessions_json=json.dumps([{"day": "Monday", "session_type": "HIIT"}]),
        generated_structure_json=json.dumps([{"day": "Monday", "session_type": "HIIT"}]),
        pushed_event_ids_json=json.dumps({"Monday": "evt-1"}),
    )

    result = regenerate_macro_plan(plan_repo, metrics_repo, "10K", NEW_RACE_DATE, TODAY)

    by_month = {m["month_start_date"]: m for m in result["months"]}
    assert by_month["2026-02-01"]["written"] is True
    assert by_month["2026-02-01"]["stale_week_structure"] is True

    # March has no generated structure at all -- no staleness to warn about.
    assert by_month["2026-03-01"]["stale_week_structure"] is False
