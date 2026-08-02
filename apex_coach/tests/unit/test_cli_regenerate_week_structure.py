import json
import os
from unittest.mock import patch

from click.testing import CliRunner

from apex_coach.cli.main import cli
from apex_coach.db.engine import create_engine
from apex_coach.db.plan_repository import PlanRepository

WEEK_START = "2026-08-03"
MONTH_START = "2026-08-01"

PLAN_ARGS = [
    "--week-start", WEEK_START,
    "--monday", "HIIT",
    "--tuesday", "Zone2_Short",
    "--wednesday", "Threshold",
    "--thursday", "Rest",
    "--friday", "Strength",
    "--saturday", "Zone2_Long",
    "--sunday", "Recovery",
]


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


def _seed_profile_and_plan(runner, env):
    with patch.dict(os.environ, env, clear=True):
        profile = runner.invoke(
            cli,
            [
                "set-athlete-profile",
                "--max-hr", "190",
                "--baseline-resting-hr", "50",
                "--sex", "MALE",
            ],
        )
        assert profile.exit_code == 0, profile.output

        plan = runner.invoke(cli, ["plan-week"] + PLAN_ARGS)
        assert plan.exit_code == 0, plan.output

        target = runner.invoke(
            cli,
            [
                "set-monthly-target",
                "--month-start-date", MONTH_START,
                "--periodisation-phase", "BASE",
                "--load-target-total", "1000",
            ],
        )
        assert target.exit_code == 0, target.output


def test_regenerate_week_structure_overwrites_without_warning_when_never_pushed(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)
    _seed_profile_and_plan(runner, env)

    with patch.dict(os.environ, env, clear=True):
        gen = runner.invoke(cli, ["generate-week-structure", "--week-start", WEEK_START])
        assert gen.exit_code == 0, gen.output

        result = runner.invoke(cli, ["regenerate-week-structure", "--week-start", WEEK_START])

    assert result.exit_code == 0, result.output
    assert "Warning" not in result.output
    assert "Structure regenerated for week starting" in result.output
    assert "Monday: HIIT" in result.output

    engine = create_engine(str(db_path))
    week = PlanRepository(engine).get_weekly_plan(WEEK_START)
    assert week["generated_structure_json"]
    assert len(json.loads(week["generated_structure_json"])) == 7


def test_regenerate_week_structure_warns_when_already_pushed(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)
    _seed_profile_and_plan(runner, env)

    with patch.dict(os.environ, env, clear=True):
        gen = runner.invoke(cli, ["generate-week-structure", "--week-start", WEEK_START])
        assert gen.exit_code == 0, gen.output

    engine = create_engine(str(db_path))
    plan_repo = PlanRepository(engine)
    plan_repo.update_weekly_plan(
        WEEK_START,
        pushed_event_ids_json=json.dumps({"Monday": "fake-event-1"}),
    )

    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["regenerate-week-structure", "--week-start", WEEK_START])

    assert result.exit_code == 0, result.output
    assert "Warning" in result.output
    assert "stale" in result.output
    assert "push-week" in result.output
    assert "Structure regenerated for week starting" in result.output


def test_regenerate_week_structure_overwrites_stale_generated_structure(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)
    _seed_profile_and_plan(runner, env)

    with patch.dict(os.environ, env, clear=True):
        gen = runner.invoke(cli, ["generate-week-structure", "--week-start", WEEK_START])
        assert gen.exit_code == 0, gen.output

    engine = create_engine(str(db_path))
    plan_repo = PlanRepository(engine)
    before = plan_repo.get_weekly_plan(WEEK_START)["generated_structure_json"]

    # Overwrite with a bogus value to prove regenerate replaces it rather
    # than treating an already-generated week as a no-op (unlike
    # `generate-week-structure`).
    plan_repo.update_weekly_plan(WEEK_START, generated_structure_json=json.dumps([]))
    assert plan_repo.get_weekly_plan(WEEK_START)["generated_structure_json"] == "[]"

    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["regenerate-week-structure", "--week-start", WEEK_START])

    assert result.exit_code == 0, result.output

    after = plan_repo.get_weekly_plan(WEEK_START)["generated_structure_json"]
    assert after != "[]"
    assert json.loads(after) == json.loads(before)


def test_regenerate_week_structure_requires_stored_plan(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)

    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["regenerate-week-structure", "--week-start", "2099-01-05"])

    assert result.exit_code != 0
    assert "no weekly plan stored" in result.output


def test_regenerate_week_structure_requires_planned_sessions(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)

    with patch.dict(os.environ, env, clear=True):
        profile = runner.invoke(
            cli,
            [
                "set-athlete-profile",
                "--max-hr", "190",
                "--baseline-resting-hr", "50",
                "--sex", "MALE",
            ],
        )
        assert profile.exit_code == 0, profile.output

        result = runner.invoke(cli, ["regenerate-week-structure", "--week-start", "2099-01-05"])

    assert result.exit_code != 0
    assert "no weekly plan stored" in result.output


def test_regenerate_week_structure_requires_athlete_profile(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)

    with patch.dict(os.environ, env, clear=True):
        plan = runner.invoke(cli, ["plan-week"] + PLAN_ARGS)
        assert plan.exit_code == 0, plan.output

        result = runner.invoke(cli, ["regenerate-week-structure", "--week-start", WEEK_START])

    assert result.exit_code != 0
    assert "set-athlete-profile" in result.output
