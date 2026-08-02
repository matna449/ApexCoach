import os
from unittest.mock import patch

from click.testing import CliRunner

from apex_coach.cli.main import cli

TODAY = "2026-01-05"  # Monday
RACE_DATE = "2026-03-09"  # exactly 9 weeks out -- 5K's minimum block length


def _env(db_path):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": "test",
        "DATABASE_URL": f"sqlite:///{db_path}",
    }


def test_preview_macro_plan_prints_every_month_and_writes_nothing(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])

        result = runner.invoke(
            cli,
            [
                "preview-macro-plan",
                "--distance", "5K",
                "--race-date", RACE_DATE,
                "--today", TODAY,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "5K" in result.output
        assert "2026-01-01" in result.output
        assert "2026-02-01" in result.output
        assert "2026-03-01" in result.output

        show_result = runner.invoke(
            cli, ["set-monthly-target", "--month-start-date", "2026-01-01", "--show"]
        )

    assert "No monthly target stored" in show_result.output


def test_preview_macro_plan_rejects_too_short_notice(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])

        result = runner.invoke(
            cli,
            [
                "preview-macro-plan",
                "--distance", "MARATHON",
                "--race-date", "2026-01-26",
                "--today", TODAY,
            ],
        )

    assert result.exit_code != 0
    assert "MARATHON" in result.output


def test_accept_macro_plan_writes_race_goal_and_monthly_targets(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])

        result = runner.invoke(
            cli,
            [
                "accept-macro-plan",
                "--distance", "5K",
                "--race-date", RACE_DATE,
                "--today", TODAY,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "created" in result.output.lower()

        goal_result = runner.invoke(cli, ["set-race-goal", "--show"])
        target_result = runner.invoke(
            cli, ["set-monthly-target", "--month-start-date", "2026-01-01", "--show"]
        )

    assert "Goal distance: 5K" in goal_result.output
    assert "Month start date: 2026-01-01" in target_result.output
    assert "Periodisation phase: BASE" in target_result.output


def test_accept_macro_plan_leaves_an_already_customized_month_untouched(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])
        runner.invoke(
            cli,
            [
                "set-monthly-target",
                "--month-start-date",
                "2026-02-01",
                "--periodisation-phase",
                "RECOVERY",
                "--load-target-total",
                "50",
            ],
        )

        result = runner.invoke(
            cli,
            [
                "accept-macro-plan",
                "--distance", "5K",
                "--race-date", RACE_DATE,
                "--today", TODAY,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "left as-is" in result.output.lower()

        show_result = runner.invoke(
            cli, ["set-monthly-target", "--month-start-date", "2026-02-01", "--show"]
        )

    assert "Periodisation phase: RECOVERY" in show_result.output
    assert "Load target total: 50.0" in show_result.output


def test_accept_macro_plan_rejects_a_second_active_goal_without_replace(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])
        runner.invoke(
            cli,
            [
                "accept-macro-plan",
                "--distance", "5K",
                "--race-date", RACE_DATE,
                "--today", TODAY,
            ],
        )

        result = runner.invoke(
            cli,
            [
                "accept-macro-plan",
                "--distance", "10K",
                "--race-date", "2026-04-01",
                "--today", TODAY,
            ],
        )

    assert result.exit_code != 0
    assert "already exists" in result.output


def test_accept_macro_plan_replace_supersedes_the_active_goal(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])
        runner.invoke(
            cli,
            [
                "accept-macro-plan",
                "--distance", "5K",
                "--race-date", RACE_DATE,
                "--today", TODAY,
            ],
        )

        result = runner.invoke(
            cli,
            [
                "accept-macro-plan",
                "--distance",
                "10K",
                "--race-date",
                "2026-04-13",
                "--today", TODAY,
                "--replace",
            ],
        )
        assert result.exit_code == 0, result.output

        goal_result = runner.invoke(cli, ["set-race-goal", "--show"])

    assert "Goal distance: 10K" in goal_result.output


def test_accept_macro_plan_rejects_too_short_notice(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])

        result = runner.invoke(
            cli,
            [
                "accept-macro-plan",
                "--distance", "MARATHON",
                "--race-date", "2026-01-26",
                "--today", TODAY,
            ],
        )
        assert result.exit_code != 0

        goal_result = runner.invoke(cli, ["set-race-goal", "--show"])

    assert "No active race goal" in goal_result.output
