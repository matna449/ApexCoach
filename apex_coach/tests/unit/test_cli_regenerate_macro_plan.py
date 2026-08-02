import json
import os
from unittest.mock import patch

from click.testing import CliRunner

from apex_coach.cli.main import cli
from apex_coach.db.engine import create_engine
from apex_coach.db.plan_repository import PlanRepository

TODAY = "2026-01-05"  # Monday
INITIAL_RACE_DATE = "2026-03-09"  # 5K's exact 9-week minimum from TODAY
NEW_RACE_DATE = "2026-05-04"  # 10K, 17 weeks out from TODAY


def _env(db_path):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": "test",
        "DATABASE_URL": f"sqlite:///{db_path}",
    }


def _init_db(runner, env):
    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["init-db"])
    assert result.exit_code == 0


def _accept_initial_plan(runner, env):
    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(
            cli,
            [
                "accept-macro-plan",
                "--distance", "5K",
                "--race-date", INITIAL_RACE_DATE,
                "--today", TODAY,
            ],
        )
    assert result.exit_code == 0, result.output


def test_regenerate_macro_plan_requires_an_active_goal(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)

    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(
            cli,
            [
                "regenerate-macro-plan",
                "--distance", "10K",
                "--race-date", NEW_RACE_DATE,
                "--today", TODAY,
            ],
        )

    assert result.exit_code != 0
    assert "accept-macro-plan" in result.output


def test_regenerate_macro_plan_with_a_changed_race_date_updates_the_goal(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)
    _accept_initial_plan(runner, env)

    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(
            cli,
            [
                "regenerate-macro-plan",
                "--distance", "10K",
                "--race-date", NEW_RACE_DATE,
                "--today", TODAY,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "2026-05-01" in result.output

        goal_result = runner.invoke(cli, ["set-race-goal", "--show"])

    assert "Goal distance: 10K" in goal_result.output
    assert f"Target race date: {NEW_RACE_DATE}" in goal_result.output


def test_regenerate_macro_plan_leaves_the_current_month_untouched(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)
    _accept_initial_plan(runner, env)

    engine = create_engine(str(db_path))
    plan_repo = PlanRepository(engine)
    january_before = plan_repo.get_monthly_target("2026-01-01")

    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(
            cli,
            [
                "regenerate-macro-plan",
                "--distance", "10K",
                "--race-date", NEW_RACE_DATE,
                "--today", TODAY,
            ],
        )

    assert result.exit_code == 0, result.output
    assert "2026-01-01" not in result.output

    january_after = plan_repo.get_monthly_target("2026-01-01")
    assert january_after == january_before


def test_regenerate_macro_plan_leaves_an_already_customized_month_untouched(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)
    _accept_initial_plan(runner, env)

    with patch.dict(os.environ, env, clear=True):
        # Athlete hand-edits March after the original accept.
        hand_edit = runner.invoke(
            cli,
            [
                "set-monthly-target",
                "--month-start-date", "2026-03-01",
                "--periodisation-phase", "RECOVERY",
                "--load-target-total", "25",
            ],
        )
        assert hand_edit.exit_code == 0, hand_edit.output

        result = runner.invoke(
            cli,
            [
                "regenerate-macro-plan",
                "--distance", "10K",
                "--race-date", NEW_RACE_DATE,
                "--today", TODAY,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "2026-03-01: left as-is" in result.output

        show_result = runner.invoke(
            cli, ["set-monthly-target", "--month-start-date", "2026-03-01", "--show"]
        )

    assert "Periodisation phase: RECOVERY" in show_result.output
    assert "Load target total: 25.0" in show_result.output


def test_regenerate_macro_plan_warns_when_touching_an_already_generated_week(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)
    _accept_initial_plan(runner, env)

    engine = create_engine(str(db_path))
    plan_repo = PlanRepository(engine)
    # February already has a generated (and pushed) week structure from
    # the original 5K block.
    plan_repo.insert_weekly_plan(
        week_start_date="2026-02-02",
        planned_sessions_json=json.dumps([{"day": "Monday", "session_type": "HIIT"}]),
        generated_structure_json=json.dumps([{"day": "Monday", "session_type": "HIIT"}]),
        pushed_event_ids_json=json.dumps({"Monday": "evt-1"}),
    )

    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(
            cli,
            [
                "regenerate-macro-plan",
                "--distance", "10K",
                "--race-date", NEW_RACE_DATE,
                "--today", TODAY,
            ],
        )

    assert result.exit_code == 0, result.output
    assert "Warning" in result.output
    assert "stale" in result.output
    assert "regenerate-week-structure" in result.output
