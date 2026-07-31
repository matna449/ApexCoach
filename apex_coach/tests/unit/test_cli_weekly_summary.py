import json
import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from apex_coach.cli.main import cli
from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.plan_repository import PlanRepository

WEEK_START = "2026-08-03"  # a Monday


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


def _plan_week(runner, db_path, **days):
    week_start = days.pop("week_start", WEEK_START)
    all_days = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
    for day in all_days - days.keys():
        days[day] = "Rest"
    args = ["plan-week", "--week-start", week_start]
    for day, session_type in days.items():
        args += [f"--{day}", session_type]
    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(cli, args)
    assert result.exit_code == 0, result.output


def test_weekly_summary_full_chain_reschedules_missed_key_session(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)
    _plan_week(
        runner,
        db_path,
        monday="HIIT",
        tuesday="Zone2_Short",
        wednesday="Strength",
        thursday="Rest",
        friday="Threshold",
        saturday="Zone2_Long",
        sunday="Rest",
    )
    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli,
            [
                "set-monthly-target",
                "--month-start-date",
                "2026-08-01",
                "--periodisation-phase",
                "BUILD",
                "--load-target-total",
                "500",
            ],
        )
        assert result.exit_code == 0, result.output

    # Tuesday's Zone2_Short was actually completed (a real activity was
    # synced) — Monday's HIIT was not, and has already passed by Wednesday.
    engine = create_engine(str(db_path))
    metrics_repo = MetricsRepository(engine)
    metrics_repo.insert_daily_metrics(date="2026-08-04")
    metrics_repo.save_activity(
        strava_id="111",
        date="2026-08-04",
        activity_type="Run",
        intended_session_type="Zone2_Short",
        duration_seconds=1800,
        distance_metres=5000,
        avg_hr_bpm=140,
    )
    activity = metrics_repo.get_activity("111")
    metrics_repo.insert_session_score(activity_id=activity["id"], execution_score=88.0)

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli, ["weekly-summary", "--week-start", WEEK_START, "--today", "2026-08-05"]
        )

    assert result.exit_code == 0, result.output
    assert "LOAD_DEFICIT" in result.output
    assert "Monday: HIIT -> Strength" in result.output
    assert "Monday HIIT" in result.output and "rescheduled" in result.output
    assert "Average execution score this week: 88.0 (1 scored session(s))" in result.output

    row = PlanRepository(engine).get_weekly_plan(WEEK_START)
    assert row["week_status"] == "LOAD_DEFICIT"
    assert row["load_actual"] > 0  # the real Zone2_Short activity's load_score
    assert row["load_target"] == pytest.approx(500 / 4.33)
    adapted = json.loads(row["adapted_plan_json"])
    assert {"day": "Monday", "session_type": "Strength"} in adapted
    assert {"day": "Wednesday", "session_type": "HIIT"} in adapted
    skipped = json.loads(row["skipped_sessions"])
    assert skipped == [{"session_type": "HIIT", "disposition": "rescheduled", "original_day": "Monday"}]


def test_weekly_summary_errors_cleanly_without_a_plan(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli, ["weekly-summary", "--week-start", WEEK_START, "--today", "2026-08-05"]
        )

    assert result.exit_code != 0
    assert "run `plan-week` first" in result.output


def test_weekly_summary_no_monthly_target_prints_no_target_message(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)
    _plan_week(runner, db_path, monday="Rest", tuesday="Rest")

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli, ["weekly-summary", "--week-start", WEEK_START, "--today", "2026-08-05"]
        )

    assert result.exit_code == 0, result.output
    assert "no monthly target set" in result.output


def test_weekly_summary_surfaces_abort_decisions(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)
    _plan_week(runner, db_path, monday="HIIT")

    engine = create_engine(str(db_path))
    plan_repo = PlanRepository(engine)
    MetricsRepository(engine).insert_daily_metrics(date="2026-08-03")
    plan_repo.insert_decision(
        date="2026-08-03", scheduled_session="HIIT", recommendation="ABORT"
    )

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli, ["weekly-summary", "--week-start", WEEK_START, "--today", "2026-08-05"]
        )

    assert result.exit_code == 0, result.output
    assert "Daily engine recommended ABORT on: Monday" in result.output


def test_weekly_summary_idempotent_on_second_run_same_day(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)
    _plan_week(runner, db_path, monday="HIIT", wednesday="Strength")

    with patch.dict(os.environ, _env(db_path), clear=True):
        first = runner.invoke(
            cli, ["weekly-summary", "--week-start", WEEK_START, "--today", "2026-08-05"]
        )
        second = runner.invoke(
            cli, ["weekly-summary", "--week-start", WEEK_START, "--today", "2026-08-05"]
        )

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert first.output == second.output

    engine = create_engine(str(db_path))
    row = PlanRepository(engine).get_weekly_plan(WEEK_START)
    skipped = json.loads(row["skipped_sessions"])
    assert len(skipped) == 1  # not re-flagged a second time
