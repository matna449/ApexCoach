import pytest
import sqlalchemy as sa

from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.plan_repository import PlanRepository
from apex_coach.db.schema import metadata


@pytest.fixture
def repo():
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    return PlanRepository(engine)


@pytest.fixture
def metrics_repo(repo):
    return MetricsRepository(repo._engine)


# -- weekly_plans -----------------------------------------------------------


def test_insert_and_get_weekly_plan(repo):
    repo.insert_weekly_plan(week_start_date="2026-07-27", load_target=300.0)

    row = repo.get_weekly_plan("2026-07-27")
    assert row["load_target"] == 300.0
    assert row["week_status"] is None


def test_get_weekly_plan_missing_returns_none(repo):
    assert repo.get_weekly_plan("2026-01-01") is None


def test_insert_weekly_plan_rejects_duplicate_week(repo):
    repo.insert_weekly_plan(week_start_date="2026-07-27")
    with pytest.raises(sa.exc.IntegrityError):
        repo.insert_weekly_plan(week_start_date="2026-07-27")


def test_update_weekly_plan_mutates_in_place_and_bumps_updated_at(repo):
    repo.insert_weekly_plan(week_start_date="2026-07-27", load_actual=0.0)

    repo.update_weekly_plan("2026-07-27", load_actual=45.0, week_status="ON_TRACK")

    row = repo.get_weekly_plan("2026-07-27")
    assert row["load_actual"] == 45.0
    assert row["week_status"] == "ON_TRACK"
    assert row["updated_at"] is not None


def test_update_weekly_plan_raises_for_unknown_week(repo):
    with pytest.raises(ValueError):
        repo.update_weekly_plan("2026-01-01", load_actual=10.0)


def test_weekly_plan_week_status_check_constraint_rejects_bad_value(repo):
    with pytest.raises(sa.exc.IntegrityError):
        repo.insert_weekly_plan(week_start_date="2026-07-27", week_status="NOT_REAL")


# -- monthly_targets --------------------------------------------------------


def test_insert_and_get_monthly_target(repo):
    repo.insert_monthly_target(
        month_start_date="2026-07-01", load_target_total=1200.0
    )

    row = repo.get_monthly_target("2026-07-01")
    assert row["load_target_total"] == 1200.0


def test_update_monthly_target_mutates_in_place_and_bumps_updated_at(repo):
    repo.insert_monthly_target(month_start_date="2026-07-01", load_actual_total=0.0)

    repo.update_monthly_target("2026-07-01", load_actual_total=300.0)

    row = repo.get_monthly_target("2026-07-01")
    assert row["load_actual_total"] == 300.0
    assert row["updated_at"] is not None


def test_update_monthly_target_raises_for_unknown_month(repo):
    with pytest.raises(ValueError):
        repo.update_monthly_target("2026-01-01", load_actual_total=10.0)


def test_insert_monthly_target_rejects_duplicate_month(repo):
    repo.insert_monthly_target(month_start_date="2026-07-01")
    with pytest.raises(sa.exc.IntegrityError):
        repo.insert_monthly_target(month_start_date="2026-07-01")


def test_upsert_monthly_target_creates_when_no_row_exists(repo):
    created = repo.upsert_monthly_target("2026-07-01", "BASE", 300.0, "2026-09-01")

    assert created is True
    row = repo.get_monthly_target("2026-07-01")
    assert row["periodisation_phase"] == "BASE"
    assert row["load_target_total"] == 300.0
    assert row["race_date"] == "2026-09-01"


def test_upsert_monthly_target_updates_when_row_already_exists(repo):
    repo.insert_monthly_target(
        month_start_date="2026-07-01", periodisation_phase="BASE", load_target_total=300.0
    )

    created = repo.upsert_monthly_target("2026-07-01", "BUILD", 400.0, None)

    assert created is False
    row = repo.get_monthly_target("2026-07-01")
    assert row["periodisation_phase"] == "BUILD"
    assert row["load_target_total"] == 400.0
    assert row["race_date"] is None


def test_upsert_monthly_target_defaults_source_to_athlete(repo):
    repo.upsert_monthly_target("2026-07-01", "BASE", 300.0)

    assert repo.get_monthly_target("2026-07-01")["source"] == "ATHLETE"


def test_upsert_monthly_target_accepts_explicit_macro_plan_source(repo):
    repo.upsert_monthly_target("2026-07-01", "BASE", 300.0, source="MACRO_PLAN")

    assert repo.get_monthly_target("2026-07-01")["source"] == "MACRO_PLAN"


def test_monthly_target_source_check_constraint_rejects_bad_value(repo):
    with pytest.raises(sa.exc.IntegrityError):
        repo.insert_monthly_target(
            month_start_date="2026-07-01", periodisation_phase="BASE", source="NOT_REAL"
        )


# -- race_goals ---------------------------------------------------------------


def test_insert_and_get_active_race_goal(repo):
    repo.insert_race_goal(
        goal_distance="HALF_MARATHON", target_race_date="2026-11-01", status="ACTIVE"
    )

    goal = repo.get_active_race_goal()
    assert goal["goal_distance"] == "HALF_MARATHON"
    assert goal["target_race_date"] == "2026-11-01"
    assert goal["status"] == "ACTIVE"


def test_get_active_race_goal_returns_none_when_no_active_row(repo):
    assert repo.get_active_race_goal() is None

    repo.insert_race_goal(
        goal_distance="5K", target_race_date="2026-09-01", status="ABANDONED"
    )
    assert repo.get_active_race_goal() is None


def test_insert_race_goal_rejects_a_second_active_row(repo):
    repo.insert_race_goal(
        goal_distance="5K", target_race_date="2026-09-01", status="ACTIVE"
    )
    with pytest.raises(ValueError):
        repo.insert_race_goal(
            goal_distance="MARATHON", target_race_date="2027-04-01", status="ACTIVE"
        )


def test_insert_race_goal_allows_a_second_abandoned_row(repo):
    repo.insert_race_goal(
        goal_distance="5K", target_race_date="2026-09-01", status="ABANDONED"
    )
    # Doesn't raise -- the unique constraint only applies to ACTIVE rows.
    repo.insert_race_goal(
        goal_distance="10K", target_race_date="2026-10-01", status="ABANDONED"
    )


def test_update_race_goal_status(repo):
    goal_id = repo.insert_race_goal(
        goal_distance="MARATHON", target_race_date="2027-04-01", status="ACTIVE"
    )

    repo.update_race_goal_status(goal_id, "ABANDONED")

    assert repo.get_active_race_goal() is None
    # A second ACTIVE goal can now be created since the first is no longer active.
    repo.insert_race_goal(
        goal_distance="10K", target_race_date="2026-10-01", status="ACTIVE"
    )


def test_update_race_goal_status_raises_for_unknown_id(repo):
    with pytest.raises(ValueError):
        repo.update_race_goal_status("does-not-exist", "ABANDONED")


def test_race_goal_distance_check_constraint_rejects_bad_value(repo):
    with pytest.raises(sa.exc.IntegrityError):
        repo.insert_race_goal(
            goal_distance="ULTRA", target_race_date="2026-09-01", status="ACTIVE"
        )


def test_race_goal_status_check_constraint_rejects_bad_value(repo):
    with pytest.raises(sa.exc.IntegrityError):
        repo.insert_race_goal(
            goal_distance="5K", target_race_date="2026-09-01", status="NOT_REAL"
        )


# -- decisions ----------------------------------------------------------------


def test_insert_and_get_decision(repo, metrics_repo):
    metrics_repo.insert_daily_metrics(date="2026-07-30")
    repo.insert_decision(date="2026-07-30", recommendation="GO")

    row = repo.get_decision("2026-07-30")
    assert row["recommendation"] == "GO"
    assert row["athlete_override"] is None


def test_insert_decision_rejects_athlete_override_field(repo, metrics_repo):
    metrics_repo.insert_daily_metrics(date="2026-07-30")
    with pytest.raises(ValueError):
        repo.insert_decision(
            date="2026-07-30", recommendation="GO", athlete_override="WENT_ANYWAY"
        )


def test_record_athlete_override_sets_override_without_touching_recommendation(
    repo, metrics_repo
):
    metrics_repo.insert_daily_metrics(date="2026-07-30")
    decision_id = repo.insert_decision(date="2026-07-30", recommendation="ABORT")

    repo.record_athlete_override(decision_id, "WENT_ANYWAY")

    row = repo.get_decision("2026-07-30")
    assert row["athlete_override"] == "WENT_ANYWAY"
    assert row["recommendation"] == "ABORT"


def test_record_athlete_override_raises_for_unknown_decision(repo):
    with pytest.raises(ValueError):
        repo.record_athlete_override("does-not-exist", "WENT_ANYWAY")


def test_get_decision_returns_most_recent_when_multiple_rows_exist(repo, metrics_repo):
    metrics_repo.insert_daily_metrics(date="2026-07-30")
    repo.insert_decision(date="2026-07-30", recommendation="MODIFY")
    repo.insert_decision(date="2026-07-30", recommendation="ABORT")

    assert repo.get_decision("2026-07-30")["recommendation"] == "ABORT"


def test_decision_recommendation_check_constraint_rejects_bad_value(repo, metrics_repo):
    metrics_repo.insert_daily_metrics(date="2026-07-30")
    with pytest.raises(sa.exc.IntegrityError):
        repo.insert_decision(date="2026-07-30", recommendation="NOT_REAL")


def test_decision_requires_existing_daily_metrics_date(repo):
    with pytest.raises(sa.exc.IntegrityError):
        repo.insert_decision(date="2026-07-30", recommendation="GO")
