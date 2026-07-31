import json
import os
from unittest.mock import patch

from click.testing import CliRunner

from apex_coach.cli.main import cli
from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.plan_repository import PlanRepository

MONTH_START = "2026-08-01"


def _env(db_path):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": "test",
        "DATABASE_URL": f"sqlite:///{db_path}",
    }


def _init_db(runner, db_path):
    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(cli, ["init-db"])
    assert result.exit_code == 0


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


def test_monthly_summary_full_chain_persists_and_prints_summary(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    engine = create_engine(str(db_path))
    plan_repo = PlanRepository(engine)
    metrics_repo = MetricsRepository(engine)

    plan_repo.insert_monthly_target(
        month_start_date=MONTH_START, periodisation_phase="BUILD", load_target_total=1000.0
    )
    _seed_activity_with_score(metrics_repo, "2026-08-03", "s1", 91.2, overpush=True)
    _seed_activity_with_score(metrics_repo, "2026-08-10", "s2", 70.0)
    metrics_repo.upsert_daily_metrics("2026-08-04", whoop_hrv_ms=74.0)
    metrics_repo.upsert_daily_metrics("2026-08-11", whoop_hrv_ms=72.0)
    plan_repo.insert_weekly_plan(
        week_start_date="2026-08-03",
        planned_sessions_json=json.dumps([{"day": "Monday", "session_type": "HIIT"}]),
        skipped_sessions=json.dumps(
            [{"session_type": "HIIT", "disposition": "written_off", "original_day": "Monday"}]
        ),
        week_status="ON_TRACK",
    )

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli,
            ["monthly-summary", "--month-start-date", MONTH_START, "--today", "2026-08-25"],
        )

    assert result.exit_code == 0, result.output
    assert "August 2026 (BUILD)" in result.output
    assert "Sessions: 2 completed, 1 skipped (1 written off), 0 recovery week(s)" in result.output
    assert "Overpush flags: 1, Underpush flags: 0" in result.output
    assert "Best session: Threshold (score 91.2)" in result.output
    assert "Threshold sessions consistently overpush" in result.output

    row = plan_repo.get_monthly_target(MONTH_START)
    assert row["load_actual_total"] > 0
    stored_summary = json.loads(row["month_summary_json"])
    assert stored_summary["sessions_completed"] == 2
    assert json.loads(row["hrv_trend_json"]) == stored_summary["hrv_weekly_avgs_ms"]


def test_monthly_summary_errors_cleanly_without_a_monthly_target(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli,
            ["monthly-summary", "--month-start-date", MONTH_START, "--today", "2026-08-25"],
        )

    assert result.exit_code != 0
    assert "no monthly_targets row" in result.output


def test_monthly_summary_handles_a_month_with_no_activity_yet(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    engine = create_engine(str(db_path))
    PlanRepository(engine).insert_monthly_target(
        month_start_date=MONTH_START, periodisation_phase="BASE", load_target_total=500.0
    )

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli,
            ["monthly-summary", "--month-start-date", MONTH_START, "--today", "2026-08-02"],
        )

    assert result.exit_code == 0, result.output
    assert "Sessions: 0 completed, 0 skipped (0 written off), 0 recovery week(s)" in result.output
    assert "Best session:" not in result.output
    assert "Worst session:" not in result.output
