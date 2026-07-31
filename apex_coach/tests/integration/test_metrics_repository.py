import pytest
import sqlalchemy as sa

from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.schema import activities as activities_table
from apex_coach.db.schema import metadata


@pytest.fixture
def repo():
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    return MetricsRepository(engine)


# -- daily_metrics --------------------------------------------------------


def test_insert_and_get_daily_metrics(repo):
    repo.insert_daily_metrics(date="2026-07-30", whoop_recovery_pct=72.0, whoop_hrv_ms=55.0)

    row = repo.get_daily_metrics("2026-07-30")

    assert row["date"] == "2026-07-30"
    assert row["whoop_recovery_pct"] == 72.0
    assert row["id"] is not None


def test_get_daily_metrics_missing_date_returns_none(repo):
    assert repo.get_daily_metrics("2026-01-01") is None


def test_insert_daily_metrics_rejects_duplicate_date(repo):
    repo.insert_daily_metrics(date="2026-07-30")
    with pytest.raises(sa.exc.IntegrityError):
        repo.insert_daily_metrics(date="2026-07-30")


def test_upsert_daily_metrics_inserts_when_no_row_exists(repo):
    repo.upsert_daily_metrics("2026-07-30", muscle_soreness=3)

    row = repo.get_daily_metrics("2026-07-30")
    assert row["muscle_soreness"] == 3


def test_upsert_daily_metrics_fills_in_columns_from_a_second_writer(repo):
    repo.insert_daily_metrics(date="2026-07-30", whoop_recovery_pct=72.0)

    repo.upsert_daily_metrics("2026-07-30", muscle_soreness=3)

    row = repo.get_daily_metrics("2026-07-30")
    assert row["whoop_recovery_pct"] == 72.0
    assert row["muscle_soreness"] == 3


def test_upsert_daily_metrics_rejects_empty_fields(repo):
    with pytest.raises(ValueError):
        repo.upsert_daily_metrics("2026-07-30")


def test_upsert_daily_metrics_rejects_immutable_fields(repo):
    with pytest.raises(ValueError):
        repo.upsert_daily_metrics("2026-07-30", id="some-id")
    with pytest.raises(ValueError):
        repo.upsert_daily_metrics("2026-07-30", created_at="2026-01-01T00:00:00")


def test_get_daily_metrics_range_is_inclusive_and_ordered(repo):
    for date in ["2026-07-01", "2026-07-15", "2026-07-30", "2026-08-01"]:
        repo.insert_daily_metrics(date=date)

    rows = repo.get_daily_metrics_range("2026-07-01", "2026-07-30")

    assert [r["date"] for r in rows] == ["2026-07-01", "2026-07-15", "2026-07-30"]


# -- hr_zones ---------------------------------------------------------------


def test_insert_and_get_hr_zones(repo):
    repo.insert_daily_metrics(date="2026-07-30")
    repo.insert_hr_zones(date="2026-07-30", max_hr_bpm=192, rest_hr_bpm=48)

    row = repo.get_hr_zones("2026-07-30")
    assert row["max_hr_bpm"] == 192
    assert row["rest_hr_bpm"] == 48


def test_get_hr_zones_returns_most_recent_when_multiple_rows_exist(repo):
    repo.insert_daily_metrics(date="2026-07-30")
    repo.insert_hr_zones(date="2026-07-30", rest_hr_bpm=48)
    repo.insert_hr_zones(date="2026-07-30", rest_hr_bpm=50)

    assert repo.get_hr_zones("2026-07-30")["rest_hr_bpm"] == 50


def test_hr_zones_requires_existing_daily_metrics_date(repo):
    with pytest.raises(sa.exc.IntegrityError):
        repo.insert_hr_zones(date="2026-07-30", rest_hr_bpm=48)


# -- activities ---------------------------------------------------------------


def test_save_activity_inserts_new_row(repo):
    repo.insert_daily_metrics(date="2026-07-30")
    repo.save_activity(strava_id="strava-1", date="2026-07-30", activity_type="Run")

    row = repo.get_activity("strava-1")
    assert row["activity_type"] == "Run"


def test_save_activity_upserts_on_resync(repo):
    repo.insert_daily_metrics(date="2026-07-30")
    repo.save_activity(
        strava_id="strava-1", date="2026-07-30", activity_type="Run", avg_hr_bpm=140
    )
    repo.save_activity(
        strava_id="strava-1", date="2026-07-30", activity_type="Run", avg_hr_bpm=145
    )

    with repo._engine.begin() as conn:
        count = conn.execute(
            sa.select(sa.func.count()).select_from(activities_table)
        ).scalar_one()

    assert count == 1
    assert repo.get_activity("strava-1")["avg_hr_bpm"] == 145


def test_save_activity_rejects_rpe_field(repo):
    repo.insert_daily_metrics(date="2026-07-30")
    with pytest.raises(ValueError):
        repo.save_activity(strava_id="strava-1", date="2026-07-30", rpe=7)


def test_update_activity_rpe_sets_rpe_without_touching_other_fields(repo):
    repo.insert_daily_metrics(date="2026-07-30")
    repo.save_activity(strava_id="strava-1", date="2026-07-30", activity_type="Run")

    repo.update_activity_rpe("strava-1", 7)

    row = repo.get_activity("strava-1")
    assert row["rpe"] == 7
    assert row["activity_type"] == "Run"


def test_resync_does_not_overwrite_previously_entered_rpe(repo):
    repo.insert_daily_metrics(date="2026-07-30")
    repo.save_activity(strava_id="strava-1", date="2026-07-30", avg_hr_bpm=140)
    repo.update_activity_rpe("strava-1", 7)

    repo.save_activity(strava_id="strava-1", date="2026-07-30", avg_hr_bpm=142)

    assert repo.get_activity("strava-1")["rpe"] == 7
    assert repo.get_activity("strava-1")["avg_hr_bpm"] == 142


def test_update_activity_rpe_raises_for_unknown_strava_id(repo):
    with pytest.raises(ValueError):
        repo.update_activity_rpe("does-not-exist", 5)


def test_get_activities_for_date(repo):
    repo.insert_daily_metrics(date="2026-07-30")
    repo.save_activity(strava_id="strava-1", date="2026-07-30")
    repo.save_activity(strava_id="strava-2", date="2026-07-30")

    rows = repo.get_activities_for_date("2026-07-30")
    assert {r["strava_id"] for r in rows} == {"strava-1", "strava-2"}


def test_get_activities_range_is_inclusive_and_ordered(repo):
    for date in ["2026-07-01", "2026-07-15", "2026-07-30", "2026-08-01"]:
        repo.insert_daily_metrics(date=date)
        repo.save_activity(strava_id=f"strava-{date}", date=date)

    rows = repo.get_activities_range("2026-07-01", "2026-07-30")

    assert [r["date"] for r in rows] == ["2026-07-01", "2026-07-15", "2026-07-30"]


# -- session_scores -----------------------------------------------------------


def test_insert_and_get_session_score(repo):
    repo.insert_daily_metrics(date="2026-07-30")
    repo.save_activity(strava_id="strava-1", date="2026-07-30")
    activity = repo.get_activity("strava-1")

    repo.insert_session_score(
        activity_id=activity["id"], execution_score=88.5, overpush_flag=False
    )

    row = repo.get_session_score(activity["id"])
    assert row["execution_score"] == 88.5
    assert row["overpush_flag"] is False


def test_get_session_score_returns_most_recent_when_multiple_rows_exist(repo):
    repo.insert_daily_metrics(date="2026-07-30")
    repo.save_activity(strava_id="strava-1", date="2026-07-30")
    activity_id = repo.get_activity("strava-1")["id"]

    repo.insert_session_score(activity_id=activity_id, execution_score=70.0)
    repo.insert_session_score(activity_id=activity_id, execution_score=90.0)

    assert repo.get_session_score(activity_id)["execution_score"] == 90.0


def test_session_scores_requires_existing_activity(repo):
    with pytest.raises(sa.exc.IntegrityError):
        repo.insert_session_score(activity_id="does-not-exist", execution_score=50.0)
