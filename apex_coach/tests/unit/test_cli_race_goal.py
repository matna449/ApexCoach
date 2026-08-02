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


def test_set_race_goal_creates_and_shows(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        init_result = runner.invoke(cli, ["init-db"])
        assert init_result.exit_code == 0

        set_result = runner.invoke(
            cli,
            [
                "set-race-goal",
                "--distance",
                "HALF_MARATHON",
                "--race-date",
                "2026-11-01",
            ],
        )
        assert set_result.exit_code == 0, set_result.output
        assert "HALF_MARATHON" in set_result.output
        assert "2026-11-01" in set_result.output

        show_result = runner.invoke(cli, ["set-race-goal", "--show"])

    assert show_result.exit_code == 0, show_result.output
    assert "Goal distance: HALF_MARATHON" in show_result.output
    assert "Target race date: 2026-11-01" in show_result.output
    assert "Status: ACTIVE" in show_result.output


def test_set_race_goal_show_with_no_active_goal(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])
        result = runner.invoke(cli, ["set-race-goal", "--show"])

    assert result.exit_code == 0
    assert "No active race goal" in result.output


def test_set_race_goal_rejects_a_second_active_goal_without_replace(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])
        runner.invoke(
            cli,
            ["set-race-goal", "--distance", "5K", "--race-date", "2026-09-01"],
        )

        result = runner.invoke(
            cli,
            ["set-race-goal", "--distance", "MARATHON", "--race-date", "2027-04-01"],
        )

    assert result.exit_code != 0
    assert "already exists" in result.output
    assert "--replace" in result.output


def test_set_race_goal_replace_abandons_the_old_goal_and_activates_the_new_one(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])
        runner.invoke(
            cli,
            ["set-race-goal", "--distance", "5K", "--race-date", "2026-09-01"],
        )

        replace_result = runner.invoke(
            cli,
            [
                "set-race-goal",
                "--distance",
                "MARATHON",
                "--race-date",
                "2027-04-01",
                "--replace",
            ],
        )
        assert replace_result.exit_code == 0, replace_result.output

        show_result = runner.invoke(cli, ["set-race-goal", "--show"])

    assert "Goal distance: MARATHON" in show_result.output
    assert "Target race date: 2027-04-01" in show_result.output


def test_set_race_goal_rejects_invalid_distance(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])
        result = runner.invoke(
            cli,
            ["set-race-goal", "--distance", "ULTRA", "--race-date", "2026-09-01"],
        )

    assert result.exit_code != 0
    assert "ULTRA" in result.output
    assert "distance" in result.output.lower()


def test_set_race_goal_rejects_invalid_race_date(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])
        result = runner.invoke(
            cli,
            ["set-race-goal", "--distance", "5K", "--race-date", "not-a-date"],
        )

    assert result.exit_code != 0
    assert "race-date" in result.output.lower()


def test_set_race_goal_requires_distance_and_race_date_when_not_showing(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])
        result = runner.invoke(cli, ["set-race-goal"])

    assert result.exit_code != 0
