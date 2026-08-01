import json
import os
from unittest.mock import patch

from click.testing import CliRunner

from apex_coach.cli.main import cli
from apex_coach.db.engine import create_engine
from apex_coach.db.plan_repository import PlanRepository
from apex_coach.db.token_repository import TokenRepository

WEEK_START = "2026-08-03"
MONTH_START = "2026-08-01"
ENCRYPTION_KEY = "test"

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
        "APEX_ENCRYPTION_KEY": ENCRYPTION_KEY,
        "DATABASE_URL": f"sqlite:///{db_path}",
    }


def _init_db(runner, env):
    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["init-db"])
    assert result.exit_code == 0


def _seed_profile_plan_and_target(runner, env):
    with patch.dict(os.environ, env, clear=True):
        assert runner.invoke(
            cli,
            [
                "set-athlete-profile",
                "--max-hr", "190",
                "--baseline-resting-hr", "50",
                "--sex", "MALE",
            ],
        ).exit_code == 0
        assert runner.invoke(cli, ["plan-week"] + PLAN_ARGS).exit_code == 0
        assert runner.invoke(
            cli,
            [
                "set-monthly-target",
                "--month-start-date", MONTH_START,
                "--periodisation-phase", "BASE",
                "--load-target-total", "1000",
            ],
        ).exit_code == 0


def _set_provider(db_path, provider):
    engine = create_engine(str(db_path))
    PlanRepository(engine).update_athlete_profile(activity_sync_provider=provider)


class FakePlanExportAdapter:
    """Stand-in for RealIntervalsIcuAdapter's push_session — same __call__
    trick as FakeIntervalsIcuAdapter in test_cli_sync_session.py."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        return self

    def push_session(self, event_date, structured_session, existing_event_id):
        self.calls.append((structured_session["day"], existing_event_id))
        return existing_event_id or f"fake-event-{event_date}"


def test_push_week_mock_pushes_all_sessions(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)
    _seed_profile_plan_and_target(runner, env)

    with patch.dict(os.environ, env, clear=True):
        gen = runner.invoke(cli, ["generate-week-structure", "--week-start", WEEK_START])
        assert gen.exit_code == 0, gen.output

        result = runner.invoke(cli, ["push-week", "--week-start", WEEK_START])

    assert result.exit_code == 0, result.output
    assert "Pushed 7 sessions" in result.output
    assert "Monday: pushed" in result.output

    engine = create_engine(str(db_path))
    week = PlanRepository(engine).get_weekly_plan(WEEK_START)
    event_ids = json.loads(week["pushed_event_ids_json"])
    assert set(event_ids) == {
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
    }


def test_push_week_real_dispatches_to_intervals_icu_and_updates_in_place(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)
    _seed_profile_plan_and_target(runner, env)
    _set_provider(db_path, "INTERVALS_ICU")

    engine = create_engine(str(db_path))
    TokenRepository(engine, ENCRYPTION_KEY).save_token(
        provider="INTERVALS_ICU", access_token="test-key", refresh_token="", expires_at="", scope=""
    )

    fake = FakePlanExportAdapter()

    with patch.dict(os.environ, env, clear=True):
        gen = runner.invoke(cli, ["generate-week-structure", "--week-start", WEEK_START])
        assert gen.exit_code == 0, gen.output

        with patch("apex_coach.cli.main.RealIntervalsIcuAdapter", fake):
            first = runner.invoke(cli, ["push-week", "--week-start", WEEK_START, "--real"])
            second = runner.invoke(cli, ["push-week", "--week-start", WEEK_START, "--real"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output

    first_call_ids = {day: existing for day, existing in fake.calls[:7]}
    second_call_ids = {day: existing for day, existing in fake.calls[7:]}
    assert all(existing is None for existing in first_call_ids.values())
    # Second push passes back the event id from the first push — update, not create.
    assert all(existing is not None for existing in second_call_ids.values())


def test_push_week_rejects_strava_provider(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)
    _seed_profile_plan_and_target(runner, env)
    _set_provider(db_path, "STRAVA")

    with patch.dict(os.environ, env, clear=True):
        gen = runner.invoke(cli, ["generate-week-structure", "--week-start", WEEK_START])
        assert gen.exit_code == 0, gen.output

        result = runner.invoke(cli, ["push-week", "--week-start", WEEK_START])

    assert result.exit_code != 0
    assert "only supported for intervals.icu" in result.output


def test_push_week_without_stored_key_gives_clean_error(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)
    _seed_profile_plan_and_target(runner, env)
    _set_provider(db_path, "INTERVALS_ICU")

    with patch.dict(os.environ, env, clear=True):
        gen = runner.invoke(cli, ["generate-week-structure", "--week-start", WEEK_START])
        assert gen.exit_code == 0, gen.output

        result = runner.invoke(cli, ["push-week", "--week-start", WEEK_START, "--real"])

    assert result.exit_code != 0
    assert "connect-intervals-icu" in result.output


def test_push_week_requires_generated_structure(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)
    _seed_profile_plan_and_target(runner, env)

    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["push-week", "--week-start", WEEK_START])

    assert result.exit_code != 0
    assert "generate-week-structure" in result.output


def test_push_week_requires_stored_plan(tmp_path):
    db_path = tmp_path / "test.db"
    env = _env(db_path)
    runner = CliRunner()
    _init_db(runner, env)

    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["push-week", "--week-start", "2099-01-05"])

    assert result.exit_code != 0
    assert "no weekly plan stored" in result.output
