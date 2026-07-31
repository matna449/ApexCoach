"""Unit tests for `sync-session` (F11.7): full chain from a mocked
RealStravaAdapter through load_calculator/session_scorer to persistence,
using a fake adapter so scenarios (multiple activities, missing stream,
resync) aren't constrained by MockStravaAdapter's single fixed payload.
"""

import json
import os
from datetime import datetime, timezone
from unittest.mock import patch

import sqlalchemy as sa
from click.testing import CliRunner

from apex_coach.cli.main import cli
from apex_coach.db.schema import session_scores
from apex_coach.models.pydantic_models import StravaActivity, StravaStream

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
) -> StravaActivity:
    return StravaActivity(
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


def _stream(hr_data: list[float]) -> StravaStream:
    n = len(hr_data)
    return StravaStream(
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
    assert "No new Strava activities to sync." in result.output


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

    # calculate_hr_based_load(15 min, 140 bpm, grade 0%) == 15*140*1.0/1000
    assert row["load_score"] == 2.1
    assert row["rpe"] == 4
    assert row["date"] == "2026-07-30"

    with engine.begin() as conn:
        score_row = conn.execute(
            sa.select(session_scores).where(session_scores.c.activity_id == row["id"])
        ).mappings().one()
    assert score_row["time_in_zone_pct"] == 100.0
    assert score_row["execution_score"] > 0


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
