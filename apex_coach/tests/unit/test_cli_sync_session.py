"""Unit tests for `sync-session` (F11.7): full chain from a mocked
RealStravaAdapter through load_calculator/session_scorer to persistence,
using a fake adapter so scenarios (multiple activities, missing stream,
resync) aren't constrained by MockStravaAdapter's single fixed payload.
"""

import json
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from click.testing import CliRunner

from apex_coach.cli.main import cli
from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.plan_repository import PlanRepository
from apex_coach.db.schema import session_scores
from apex_coach.db.token_repository import TokenRepository
from apex_coach.models.pydantic_models import Activity, ActivityStream

ENCRYPTION_KEY = "test-passphrase-not-for-production"


def _env(db_path):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": ENCRYPTION_KEY,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "STRAVA_CLIENT_ID": "client-id",
        "STRAVA_CLIENT_SECRET": "client-secret",
    }


def _activity(
    activity_id: int,
    activity_type: str = "Run",
    name: str = "Evening Run",
    start_date: str = "2026-07-30T06:00:00Z",
    elapsed_time: int = 900,
    distance: float = 3000.0,
    average_heartrate: float | None = 140.0,
    max_heartrate: float | None = 155.0,
) -> Activity:
    return Activity(
        id=activity_id,
        name=name,
        type=activity_type,
        start_date=start_date,
        elapsed_time=elapsed_time,
        distance=distance,
        total_elevation_gain=0.0,
        average_speed=distance / elapsed_time if elapsed_time else 0.0,
        average_heartrate=average_heartrate,
        max_heartrate=max_heartrate,
        has_heartrate=average_heartrate is not None,
    )


def _stream(hr_data: list[float]) -> ActivityStream:
    n = len(hr_data)
    return ActivityStream(
        heartrate={"data": hr_data, "series_type": "distance", "original_size": n},
        time={"data": list(range(n)), "series_type": "distance", "original_size": n},
        distance={
            "data": [float(i) for i in range(n)],
            "series_type": "distance",
            "original_size": n,
        },
    )


class FakeStravaAdapter:
    """Stand-in for RealStravaAdapter — ignores constructor args, returns
    whatever activities/streams the test configured."""

    def __init__(self, activities=None, streams=None):
        self._activities = activities or []
        self._streams = streams or {}

    def __call__(self, *args, **kwargs):
        # Allows patching RealStravaAdapter itself (a class) with an
        # already-configured instance and having `RealStravaAdapter(...)`
        # calls in the CLI return this same instance.
        return self

    def get_new_activities(self, since_ts):
        return self._activities

    def get_activity_stream(self, activity_id):
        return self._streams.get(activity_id)


def _init_db(runner, env):
    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["init-db"])
    assert result.exit_code == 0
    # TRIMP load calculation (docs/adr/0024) needs an athlete profile —
    # harmless for the RPE-based/no-activity tests in this file that don't
    # reach the HR-based load path at all.
    db_path = env["DATABASE_URL"].removeprefix("sqlite:///")
    # Pinned to STRAVA — these fixtures predate F18.6/#95's default flip to
    # INTERVALS_ICU and deliberately exercise the Strava path via
    # FakeStravaAdapter; the provider-dispatch tests below override this.
    PlanRepository(create_engine(db_path)).insert_athlete_profile(
        max_hr=190, baseline_resting_hr=50, sex="MALE", activity_sync_provider="STRAVA"
    )


def test_sync_session_no_new_activities_exits_cleanly(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "test.db")
    _init_db(runner, env)

    fake = FakeStravaAdapter(activities=[])
    with patch.dict(os.environ, env, clear=True), patch(
        "apex_coach.cli.main.RealStravaAdapter", fake
    ):
        result = runner.invoke(
            cli,
            [
                "sync-session",
                "--real",
                "--session-type",
                "Zone2_Short",
                "--max-hr",
                "190",
                "--resting-hr",
                "50",
            ],
        )

    assert result.exit_code == 0
    assert "No new activities to sync." in result.output


def test_sync_session_strength_full_chain_persists_activity_and_score(tmp_path):
    """WeightTraining/Strength needs no HR-zone target — minimal hr_data,
    exercises the RPE-based load path and the zone_boundaries=None path."""
    runner = CliRunner()
    env = _env(tmp_path / "test.db")
    _init_db(runner, env)

    activity = _activity(
        activity_id=111,
        activity_type="WeightTraining",
        name="Lower Body Strength",
        elapsed_time=3600,
        distance=0.0,
        average_heartrate=None,
        max_heartrate=None,
    )
    stream = _stream([120.0] * 60)
    fake = FakeStravaAdapter(activities=[activity], streams={111: stream})

    with patch.dict(os.environ, env, clear=True), patch(
        "apex_coach.cli.main.RealStravaAdapter", fake
    ):
        result = runner.invoke(
            cli,
            [
                "sync-session",
                "--real",
                "--session-type",
                "Strength",
                "--max-hr",
                "190",
                "--resting-hr",
                "50",
                "--rpe",
                "6",
            ],
        )

    assert result.exit_code == 0, result.output

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.begin() as conn:
        row = conn.execute(
            sa.text("SELECT * FROM activities WHERE strava_id = :sid"), {"sid": "111"}
        ).mappings().one()

    assert row["activity_type"] == "WeightTraining"
    assert row["intended_session_type"] == "Strength"
    assert row["rpe"] == 6
    # calculate_rpe_based_load(60 min, rpe=6) == 60 * 6 / 6 == 60.0
    assert row["load_score"] == 60.0
    assert row["strava_raw_json"] is not None
    assert json.loads(row["strava_raw_json"])["id"] == 111

    with engine.begin() as conn:
        score_row = conn.execute(
            sa.select(session_scores).where(session_scores.c.activity_id == row["id"])
        ).mappings().one()
    assert score_row["execution_score"] is not None
    assert score_row["time_in_zone_pct"] is None  # Strength has no HR target


def test_sync_session_run_zone2_short_computes_hr_based_load(tmp_path):
    """Run activity, Zone2_Short session — exercises the HR-based load
    formula and a real zone-bounded execution score (>600s stream)."""
    runner = CliRunner()
    env = _env(tmp_path / "test.db")
    _init_db(runner, env)

    activity = _activity(
        activity_id=222,
        activity_type="Run",
        elapsed_time=900,
        distance=3000.0,
        average_heartrate=140.0,
        max_heartrate=148.0,
    )
    stream = _stream([140.0] * 900)
    fake = FakeStravaAdapter(activities=[activity], streams={222: stream})

    with patch.dict(os.environ, env, clear=True), patch(
        "apex_coach.cli.main.RealStravaAdapter", fake
    ):
        result = runner.invoke(
            cli,
            [
                "sync-session",
                "--real",
                "--session-type",
                "Zone2_Short",
                "--max-hr",
                "190",
                "--resting-hr",
                "50",
                "--rpe",
                "4",
            ],
        )

    assert result.exit_code == 0, result.output

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.begin() as conn:
        row = conn.execute(
            sa.text("SELECT * FROM activities WHERE strava_id = :sid"), {"sid": "222"}
        ).mappings().one()

    # TRIMP (docs/adr/0024): 15 min, avg_hr=140, resting_hr=50 (no day-of
    # WHOOP reading -> profile.baseline_resting_hr fallback), max_hr=190,
    # sex=MALE. Independently computed: ratio=0.6428571..., 15*ratio*0.64*
    # e^(1.92*ratio) == 21.20455592008078
    assert row["load_score"] == pytest.approx(21.20455592008078)
    assert row["rpe"] == 4
    assert row["date"] == "2026-07-30"

    with engine.begin() as conn:
        score_row = conn.execute(
            sa.select(session_scores).where(session_scores.c.activity_id == row["id"])
        ).mappings().one()
    assert score_row["time_in_zone_pct"] == 100.0
    assert score_row["execution_score"] > 0


def test_sync_session_prefers_day_of_whoop_resting_hr_over_profile(tmp_path):
    """docs/adr/0024: TRIMP prefers the day-of WHOOP resting HR over the
    athlete profile's baseline_resting_hr (50, from _init_db) or the
    --resting-hr flag (also 50 here) — both would give a different result
    than the day-of value (45) actually used below."""
    runner = CliRunner()
    env = _env(tmp_path / "test.db")
    _init_db(runner, env)

    MetricsRepository(create_engine(str(tmp_path / "test.db"))).upsert_daily_metrics(
        "2026-07-30", whoop_rhr_bpm=45
    )

    activity = _activity(
        activity_id=223,
        activity_type="Run",
        elapsed_time=900,
        distance=3000.0,
        average_heartrate=140.0,
        max_heartrate=148.0,
    )
    stream = _stream([140.0] * 900)
    fake = FakeStravaAdapter(activities=[activity], streams={223: stream})

    with patch.dict(os.environ, env, clear=True), patch(
        "apex_coach.cli.main.RealStravaAdapter", fake
    ):
        result = runner.invoke(
            cli,
            [
                "sync-session",
                "--real",
                "--session-type",
                "Zone2_Short",
                "--max-hr",
                "190",
                "--resting-hr",
                "50",
                "--rpe",
                "4",
            ],
        )

    assert result.exit_code == 0, result.output

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.begin() as conn:
        row = conn.execute(
            sa.text("SELECT load_score FROM activities WHERE strava_id = :sid"), {"sid": "223"}
        ).mappings().one()

    # ratio=(140-45)/(190-45)=0.6551724..., 15*ratio*0.64*e^(1.92*ratio)
    assert row["load_score"] == pytest.approx(22.12785632810031)


def test_sync_session_errors_without_profile_or_flags(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "test.db")
    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["init-db"])
    assert result.exit_code == 0
    # Deliberately no athlete profile set up (unlike _init_db's default).

    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(
            cli, ["sync-session", "--real", "--session-type", "Zone2_Short", "--rpe", "4"]
        )

    assert result.exit_code != 0
    assert "set-athlete-profile" in result.output


def test_sync_session_prompts_for_rpe_when_not_given(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "test.db")
    _init_db(runner, env)

    activity = _activity(activity_id=333, elapsed_time=900, distance=3000.0)
    stream = _stream([140.0] * 900)
    fake = FakeStravaAdapter(activities=[activity], streams={333: stream})

    with patch.dict(os.environ, env, clear=True), patch(
        "apex_coach.cli.main.RealStravaAdapter", fake
    ):
        result = runner.invoke(
            cli,
            [
                "sync-session",
                "--real",
                "--session-type",
                "Zone2_Short",
                "--max-hr",
                "190",
                "--resting-hr",
                "50",
            ],
            input="5\n",
        )

    assert result.exit_code == 0, result.output
    assert "RPE for this session" in result.output

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.begin() as conn:
        row = conn.execute(
            sa.text("SELECT rpe FROM activities WHERE strava_id = :sid"), {"sid": "333"}
        ).mappings().one()
    assert row["rpe"] == 5


def test_sync_session_multiple_activities_prompts_for_selection(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "test.db")
    _init_db(runner, env)

    activity_a = _activity(activity_id=444, name="Morning Run", elapsed_time=900, distance=3000.0)
    activity_b = _activity(
        activity_id=445,
        name="Evening Ride",
        activity_type="Ride",
        elapsed_time=900,
        distance=3000.0,
    )
    stream_b = _stream([140.0] * 900)
    fake = FakeStravaAdapter(activities=[activity_a, activity_b], streams={445: stream_b})

    with patch.dict(os.environ, env, clear=True), patch(
        "apex_coach.cli.main.RealStravaAdapter", fake
    ):
        result = runner.invoke(
            cli,
            [
                "sync-session",
                "--real",
                "--session-type",
                "Zone2_Short",
                "--max-hr",
                "190",
                "--resting-hr",
                "50",
                "--rpe",
                "4",
            ],
            # Select index 1 (Evening Ride) — the one with a stream available.
            input="1\n",
        )

    assert result.exit_code == 0, result.output
    assert "Morning Run" in result.output
    assert "Evening Ride" in result.output

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.begin() as conn:
        rows = conn.execute(sa.text("SELECT strava_id FROM activities")).mappings().all()
    assert {r["strava_id"] for r in rows} == {"445"}


def test_sync_session_resync_upserts_activity_and_appends_new_score(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "test.db")
    _init_db(runner, env)

    activity = _activity(activity_id=555, elapsed_time=900, distance=3000.0)
    stream = _stream([140.0] * 900)
    fake = FakeStravaAdapter(activities=[activity], streams={555: stream})

    args = [
        "sync-session",
        "--real",
        "--session-type",
        "Zone2_Short",
        "--max-hr",
        "190",
        "--resting-hr",
        "50",
        "--rpe",
        "4",
    ]

    with patch.dict(os.environ, env, clear=True), patch(
        "apex_coach.cli.main.RealStravaAdapter", fake
    ):
        first = runner.invoke(cli, args)
        second = runner.invoke(cli, args)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.begin() as conn:
        activity_rows = conn.execute(sa.text("SELECT id FROM activities")).mappings().all()
    assert len(activity_rows) == 1  # upserted, not duplicated

    activity_id = activity_rows[0]["id"]
    with engine.begin() as conn:
        score_rows = conn.execute(
            sa.select(session_scores).where(session_scores.c.activity_id == activity_id)
        ).mappings().all()
    assert len(score_rows) == 2  # append-only per ADR-0006


def test_sync_session_missing_stream_gives_clean_error(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "test.db")
    _init_db(runner, env)

    activity = _activity(activity_id=666, elapsed_time=900, distance=3000.0)
    fake = FakeStravaAdapter(activities=[activity], streams={})

    with patch.dict(os.environ, env, clear=True), patch(
        "apex_coach.cli.main.RealStravaAdapter", fake
    ):
        result = runner.invoke(
            cli,
            [
                "sync-session",
                "--real",
                "--session-type",
                "Zone2_Short",
                "--max-hr",
                "190",
                "--resting-hr",
                "50",
                "--rpe",
                "4",
            ],
        )

    assert result.exit_code != 0
    assert "No HR stream available" in result.output


# -- activity_sync_provider dispatch (F18.4 / #93, docs/adr/0025) -----------


class FakeIntervalsIcuAdapter:
    """Stand-in for RealIntervalsIcuAdapter — same shape as FakeStravaAdapter."""

    def __init__(self, activities=None, streams=None):
        self._activities = activities or []
        self._streams = streams or {}

    def __call__(self, *args, **kwargs):
        return self

    def get_new_activities(self, since_ts):
        return self._activities

    def get_activity_stream(self, activity_id):
        return self._streams.get(activity_id)


def _set_provider(db_path, provider):
    engine = create_engine(str(db_path))
    repo = PlanRepository(engine)
    repo.update_athlete_profile(activity_sync_provider=provider)


def test_sync_session_real_dispatches_to_strava_when_configured(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "test.db")
    _init_db(runner, env)  # pins STRAVA — see _init_db's comment

    strava_activity = _activity(activity_id=201, elapsed_time=900, distance=3000.0)
    strava_fake = FakeStravaAdapter(activities=[strava_activity], streams={201: _stream([140.0] * 900)})
    icu_fake = FakeIntervalsIcuAdapter(activities=[])

    with (
        patch.dict(os.environ, env, clear=True),
        patch("apex_coach.cli.main.RealStravaAdapter", strava_fake),
        patch("apex_coach.cli.main.RealIntervalsIcuAdapter", icu_fake),
    ):
        result = runner.invoke(
            cli,
            [
                "sync-session",
                "--real",
                "--session-type",
                "Zone2_Short",
                "--max-hr",
                "190",
                "--resting-hr",
                "50",
                "--rpe",
                "4",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "Synced activity" in result.output


def test_sync_session_real_dispatches_to_intervals_icu_when_provider_unset(tmp_path):
    """F18.6/#95 — a NULL activity_sync_provider (never explicitly set)
    defaults to INTERVALS_ICU, not STRAVA."""
    runner = CliRunner()
    env = _env(tmp_path / "test.db")
    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["init-db"])
    assert result.exit_code == 0
    db_path = env["DATABASE_URL"].removeprefix("sqlite:///")
    PlanRepository(create_engine(db_path)).insert_athlete_profile(
        max_hr=190, baseline_resting_hr=50, sex="MALE"  # no activity_sync_provider
    )

    engine = create_engine(db_path)
    TokenRepository(engine, ENCRYPTION_KEY).save_token(
        provider="INTERVALS_ICU",
        access_token="fake-api-key",
        refresh_token="",
        expires_at="",
        scope="",
    )

    icu_activity = _activity(activity_id=203, elapsed_time=900, distance=3000.0)
    icu_fake = FakeIntervalsIcuAdapter(
        activities=[icu_activity], streams={203: _stream([140.0] * 900)}
    )
    strava_fake = FakeStravaAdapter(activities=[])

    with (
        patch.dict(os.environ, env, clear=True),
        patch("apex_coach.cli.main.RealStravaAdapter", strava_fake),
        patch("apex_coach.cli.main.RealIntervalsIcuAdapter", icu_fake),
    ):
        result = runner.invoke(
            cli,
            [
                "sync-session",
                "--real",
                "--session-type",
                "Zone2_Short",
                "--max-hr",
                "190",
                "--resting-hr",
                "50",
                "--rpe",
                "4",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "Synced activity" in result.output


def test_sync_session_real_dispatches_to_intervals_icu_when_configured(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "test.db")
    _init_db(runner, env)
    _set_provider(tmp_path / "test.db", "INTERVALS_ICU")

    engine = create_engine(str(tmp_path / "test.db"))
    TokenRepository(engine, ENCRYPTION_KEY).save_token(
        provider="INTERVALS_ICU",
        access_token="fake-api-key",
        refresh_token="",
        expires_at="",
        scope="",
    )

    icu_activity = _activity(activity_id=202, elapsed_time=900, distance=3000.0)
    icu_fake = FakeIntervalsIcuAdapter(
        activities=[icu_activity], streams={202: _stream([140.0] * 900)}
    )
    strava_fake = FakeStravaAdapter(activities=[])

    with (
        patch.dict(os.environ, env, clear=True),
        patch("apex_coach.cli.main.RealStravaAdapter", strava_fake),
        patch("apex_coach.cli.main.RealIntervalsIcuAdapter", icu_fake),
    ):
        result = runner.invoke(
            cli,
            [
                "sync-session",
                "--real",
                "--session-type",
                "Zone2_Short",
                "--max-hr",
                "190",
                "--resting-hr",
                "50",
                "--rpe",
                "4",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "Synced activity" in result.output


def test_sync_session_real_intervals_icu_without_stored_key_gives_clean_error(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "test.db")
    _init_db(runner, env)
    _set_provider(tmp_path / "test.db", "INTERVALS_ICU")

    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(
            cli,
            [
                "sync-session",
                "--real",
                "--session-type",
                "Zone2_Short",
                "--max-hr",
                "190",
                "--resting-hr",
                "50",
            ],
        )

    assert result.exit_code != 0
    assert "connect-intervals-icu" in result.output


def test_sync_session_mock_dispatches_to_intervals_icu_when_configured(tmp_path):
    """Without --real, dispatch still follows activity_sync_provider —
    MockIntervalsIcuAdapter's fixture activity id (987654321) rather than
    MockStravaAdapter's (12748392017)."""
    runner = CliRunner()
    env = _env(tmp_path / "test.db")
    _init_db(runner, env)
    _set_provider(tmp_path / "test.db", "INTERVALS_ICU")

    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(
            cli,
            [
                "sync-session",
                "--session-type",
                "Zone2_Short",
                "--max-hr",
                "190",
                "--resting-hr",
                "50",
                "--rpe",
                "4",
            ],
        )

    assert result.exit_code == 0, result.output
    engine = create_engine(str(tmp_path / "test.db"))
    with engine.begin() as conn:
        rows = conn.execute(sa.text("SELECT strava_id FROM activities")).mappings().all()
    assert rows[0]["strava_id"] == "i987654321"
