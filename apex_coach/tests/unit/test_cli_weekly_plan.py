import json
import os
from unittest.mock import patch

from click.testing import CliRunner

from apex_coach.cli.main import cli


def _env(db_path):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": "test",
        "DATABASE_URL": f"sqlite:///{db_path}",
    }


FULL_WEEK_ARGS = [
    "--week-start", "2026-08-03",
    "--monday", "HIIT",
    "--tuesday", "Zone2_Short",
    "--wednesday", "Threshold",
    "--thursday", "Rest",
    "--friday", "Strength",
    "--saturday", "Zone2_Long",
    "--sunday", "Recovery",
]


def _init_db(runner, db_path):
    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(cli, ["init-db"])
    assert result.exit_code == 0


def test_plan_week_persists_valid_plan(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(cli, ["plan-week"] + FULL_WEEK_ARGS)

    assert result.exit_code == 0, result.output
    assert "Plan saved for week starting 2026-08-03" in result.output
    assert "Monday: HIIT" in result.output
    assert "Thursday: Rest" in result.output

    with patch.dict(os.environ, _env(db_path), clear=True):
        show_result = runner.invoke(
            cli, ["plan-week", "--week-start", "2026-08-03", "--show"]
        )

    assert show_result.exit_code == 0, show_result.output
    assert "Monday: HIIT" in show_result.output
    assert "Sunday: Recovery" in show_result.output


def test_plan_week_rejects_invalid_session_type(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    args = list(FULL_WEEK_ARGS)
    monday_idx = args.index("--monday") + 1
    args[monday_idx] = "NotARealType"

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(cli, ["plan-week"] + args)

    assert result.exit_code != 0
    assert "Invalid value for '--monday'" in result.output


def test_plan_week_requires_all_seven_days(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    # Omit --sunday entirely.
    args = [
        "--week-start", "2026-08-03",
        "--monday", "HIIT",
        "--tuesday", "Zone2_Short",
        "--wednesday", "Threshold",
        "--thursday", "Rest",
        "--friday", "Strength",
        "--saturday", "Zone2_Long",
    ]

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(cli, ["plan-week"] + args)

    assert result.exit_code != 0
    assert "missing --session-type" in result.output
    assert "sunday" in result.output


def test_plan_week_update_overwrites_existing_week(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        first = runner.invoke(cli, ["plan-week"] + FULL_WEEK_ARGS)
    assert first.exit_code == 0, first.output

    updated_args = list(FULL_WEEK_ARGS)
    monday_idx = updated_args.index("--monday") + 1
    updated_args[monday_idx] = "Recovery"

    with patch.dict(os.environ, _env(db_path), clear=True):
        second = runner.invoke(cli, ["plan-week"] + updated_args)
    assert second.exit_code == 0, second.output
    assert "Monday: Recovery" in second.output

    # Confirm it was an overwrite, not a second row / error.
    with patch.dict(os.environ, _env(db_path), clear=True):
        show_result = runner.invoke(
            cli, ["plan-week", "--week-start", "2026-08-03", "--show"]
        )
    assert show_result.exit_code == 0, show_result.output
    assert "Monday: Recovery" in show_result.output

    import sqlalchemy as sa

    from apex_coach.db.schema import weekly_plans

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        rows = conn.execute(
            sa.select(weekly_plans).where(
                weekly_plans.c.week_start_date == "2026-08-03"
            )
        ).all()
    assert len(rows) == 1
    sessions = json.loads(rows[0]._mapping["planned_sessions_json"])
    by_day = {s["day"]: s["session_type"] for s in sessions}
    assert by_day["Monday"] == "Recovery"
    assert by_day["Sunday"] == "Recovery"


def test_plan_week_show_reports_missing_week(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli, ["plan-week", "--week-start", "2099-01-05", "--show"]
        )

    assert result.exit_code != 0
    assert "no weekly plan stored" in result.output
