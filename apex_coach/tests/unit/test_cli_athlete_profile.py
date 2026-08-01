import os
from unittest.mock import patch

from click.testing import CliRunner

from apex_coach.cli.main import cli
from apex_coach.db.engine import create_engine
from apex_coach.db.plan_repository import PlanRepository


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


def test_set_athlete_profile_creates_then_shows(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        create = runner.invoke(
            cli,
            [
                "set-athlete-profile",
                "--max-hr",
                "190",
                "--baseline-resting-hr",
                "50",
                "--sex",
                "MALE",
            ],
        )
        assert create.exit_code == 0, create.output
        assert "created" in create.output.lower()

        show = runner.invoke(cli, ["set-athlete-profile", "--show"])

    assert show.exit_code == 0, show.output
    assert "Max HR: 190" in show.output
    assert "Baseline resting HR: 50" in show.output
    assert "Sex: MALE" in show.output


def test_set_athlete_profile_show_with_no_profile_stored(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(cli, ["set-athlete-profile", "--show"])

    assert result.exit_code == 0, result.output
    assert "No athlete profile stored." in result.output


def test_set_athlete_profile_partial_update_preserves_other_fields(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(
            cli,
            [
                "set-athlete-profile",
                "--max-hr",
                "190",
                "--baseline-resting-hr",
                "50",
                "--sex",
                "MALE",
            ],
        )
        # Only update max_hr — baseline_resting_hr/sex should be preserved.
        update = runner.invoke(cli, ["set-athlete-profile", "--max-hr", "195"])

    assert update.exit_code == 0, update.output
    assert "updated" in update.output.lower()

    engine = create_engine(str(db_path))
    profile = PlanRepository(engine).get_athlete_profile()
    assert profile["max_hr"] == 195
    assert profile["baseline_resting_hr"] == 50
    assert profile["sex"] == "MALE"


def test_set_athlete_profile_rejects_invalid_sex(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(cli, ["set-athlete-profile", "--sex", "OTHER"])

    assert result.exit_code != 0


# -- activity_sync_provider (F18.4 / #93, docs/adr/0025) ---------------------


def test_set_athlete_profile_stores_activity_sync_provider(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        create = runner.invoke(
            cli, ["set-athlete-profile", "--activity-sync-provider", "INTERVALS_ICU"]
        )
        assert create.exit_code == 0, create.output

        show = runner.invoke(cli, ["set-athlete-profile", "--show"])

    assert show.exit_code == 0, show.output
    assert "Activity sync provider: INTERVALS_ICU" in show.output


def test_set_athlete_profile_show_defaults_provider_to_intervals_icu_when_unset(tmp_path):
    """F18.6/#95 — the un-configured default is INTERVALS_ICU, not STRAVA."""
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        runner.invoke(cli, ["set-athlete-profile", "--max-hr", "190"])
        show = runner.invoke(cli, ["set-athlete-profile", "--show"])

    assert show.exit_code == 0, show.output
    assert "Activity sync provider: INTERVALS_ICU" in show.output


def test_set_athlete_profile_rejects_invalid_activity_sync_provider(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli, ["set-athlete-profile", "--activity-sync-provider", "GARMIN_CONNECT"]
        )

    assert result.exit_code != 0
