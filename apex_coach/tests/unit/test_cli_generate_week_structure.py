import os
from unittest.mock import patch

from click.testing import CliRunner

from apex_coach.cli.main import cli

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


def test_generate_week_structure_persists_and_prints(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)
    _seed_profile_and_plan(runner, env)

    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["generate-week-structure", "--week-start", WEEK_START])

    assert result.exit_code == 0, result.output
    assert "Structure generated for week starting" in result.output
    assert "Monday: HIIT" in result.output
    assert "Thursday: Rest" in result.output
    assert "Friday: Strength" in result.output


def test_generate_week_structure_is_idempotent_does_not_regenerate(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)
    _seed_profile_and_plan(runner, env)

    with patch.dict(os.environ, env, clear=True):
        first = runner.invoke(cli, ["generate-week-structure", "--week-start", WEEK_START])
        second = runner.invoke(cli, ["generate-week-structure", "--week-start", WEEK_START])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert "Structure already generated for week starting" in second.output

    import sqlalchemy as sa

    from apex_coach.db.schema import weekly_plans

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        rows = conn.execute(
            sa.select(weekly_plans).where(weekly_plans.c.week_start_date == WEEK_START)
        ).all()
    assert len(rows) == 1


def test_generate_week_structure_requires_stored_plan(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)

    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["generate-week-structure", "--week-start", "2099-01-05"])

    assert result.exit_code != 0
    assert "no weekly plan stored" in result.output


def test_generate_week_structure_requires_athlete_profile(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)

    with patch.dict(os.environ, env, clear=True):
        plan = runner.invoke(cli, ["plan-week"] + PLAN_ARGS)
        assert plan.exit_code == 0, plan.output

        result = runner.invoke(cli, ["generate-week-structure", "--week-start", WEEK_START])

    assert result.exit_code != 0
    assert "set-athlete-profile" in result.output
