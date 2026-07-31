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


def test_set_monthly_target_creates_and_shows(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        init_result = runner.invoke(cli, ["init-db"])
        assert init_result.exit_code == 0

        set_result = runner.invoke(
            cli,
            [
                "set-monthly-target",
                "--month-start-date",
                "2026-08-01",
                "--periodisation-phase",
                "BUILD",
                "--load-target-total",
                "450",
                "--race-date",
                "2026-09-15",
            ],
        )
        assert set_result.exit_code == 0, set_result.output
        assert "created" in set_result.output.lower()

        show_result = runner.invoke(
            cli,
            ["set-monthly-target", "--month-start-date", "2026-08-01", "--show"],
        )

    assert show_result.exit_code == 0, show_result.output
    assert "Month start date: 2026-08-01" in show_result.output
    assert "Periodisation phase: BUILD" in show_result.output
    assert "Load target total: 450.0" in show_result.output
    assert "Race date: 2026-09-15" in show_result.output


def test_set_monthly_target_updates_existing_row(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])
        runner.invoke(
            cli,
            [
                "set-monthly-target",
                "--month-start-date",
                "2026-08-01",
                "--periodisation-phase",
                "BASE",
                "--load-target-total",
                "300",
            ],
        )

        update_result = runner.invoke(
            cli,
            [
                "set-monthly-target",
                "--month-start-date",
                "2026-08-01",
                "--periodisation-phase",
                "BUILD",
                "--load-target-total",
                "400",
            ],
        )

        show_result = runner.invoke(
            cli,
            ["set-monthly-target", "--month-start-date", "2026-08-01", "--show"],
        )

    assert update_result.exit_code == 0, update_result.output
    assert "updated" in update_result.output.lower()
    assert "Periodisation phase: BUILD" in show_result.output
    assert "Load target total: 400.0" in show_result.output


def test_set_monthly_target_rejects_invalid_periodisation_phase(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])
        result = runner.invoke(
            cli,
            [
                "set-monthly-target",
                "--month-start-date",
                "2026-08-01",
                "--periodisation-phase",
                "NOT_A_PHASE",
                "--load-target-total",
                "300",
            ],
        )

    assert result.exit_code != 0
    assert "NOT_A_PHASE" in result.output
    assert "periodisation-phase" in result.output.lower()


def test_set_monthly_target_show_with_no_stored_row(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])
        result = runner.invoke(
            cli,
            ["set-monthly-target", "--month-start-date", "2026-08-01", "--show"],
        )

    assert result.exit_code == 0
    assert "No monthly target stored" in result.output


def test_set_monthly_target_requires_phase_and_load_when_not_showing(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["init-db"])
        result = runner.invoke(
            cli,
            ["set-monthly-target", "--month-start-date", "2026-08-01"],
        )

    assert result.exit_code != 0
