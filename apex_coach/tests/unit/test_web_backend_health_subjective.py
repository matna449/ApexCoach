"""F21.7: POST /api/health/subjective. Reloads web.backend.main with a key set,
the same way the other web backend tests do."""

import importlib
import os
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.schema import metadata

ROUTE = "/api/health/subjective"
AUTH = {"Authorization": "Bearer api-key"}
DAY = "2026-10-31"


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    metadata.create_all(engine)
    return engine


@pytest.fixture
def metrics(engine):
    return MetricsRepository(engine)


@pytest.fixture
def client(engine):
    env = {
        "APEX_ENCRYPTION_KEY": "test-key",
        "DATABASE_URL": str(engine.url),
        "APEX_API_KEY": "api-key",
        "APEX_TIMEZONE": "Pacific/Auckland",
    }
    with patch.dict(os.environ, env, clear=True):
        import web.backend.main as main_module

        importlib.reload(main_module)
    return TestClient(main_module.app)


def _post(client, **body):
    return client.post(ROUTE, json=body, headers=AUTH)


def test_all_answers_land_in_their_columns(client, metrics):
    response = _post(
        client,
        date=DAY,
        rpe_yesterday=3,
        soreness="left calf",
        soreness_level=2,
        sleep_quality=2,
        energy=5,
        stress=1,
        pain="none today",
    )

    assert response.status_code == 200
    row = metrics.get_daily_metrics(DAY)
    assert row["rpe_yesterday"] == 3
    assert row["soreness_note"] == "left calf"
    assert row["muscle_soreness"] == 2
    assert row["sleep_quality_felt"] == 2
    assert row["subjective_energy"] == 5
    assert row["subjective_stress"] == 1
    assert row["pain_note"] == "none today"


def test_partial_update_keeps_whoop_columns_and_other_answers(client, metrics):
    metrics.upsert_daily_metrics(DAY, whoop_recovery_pct=62.0, whoop_hrv_ms=71.4, subjective_energy=4)

    assert _post(client, date=DAY, stress=2).status_code == 200

    row = metrics.get_daily_metrics(DAY)
    assert row["subjective_stress"] == 2
    assert row["whoop_recovery_pct"] == 62.0
    assert row["whoop_hrv_ms"] == 71.4
    assert row["subjective_energy"] == 4


def test_explicit_null_clears_an_answer_and_a_missing_field_does_not(client, metrics):
    _post(client, date=DAY, pain="knee", stress=2)

    assert _post(client, date=DAY, pain=None).status_code == 200

    row = metrics.get_daily_metrics(DAY)
    assert row["pain_note"] is None
    assert row["subjective_stress"] == 2


@pytest.mark.parametrize(
    "body",
    [
        {"rpe_yesterday": 11},
        {"rpe_yesterday": 0},
        {"soreness_level": 6},
        {"sleep_quality": 0},
        {"energy": 6},
        {"stress": 0},
        {"energy": "high"},
        {"date": "not-a-date", "energy": 3},
        {"unknown_field": 1},
        {},
        {"date": DAY},
    ],
    ids=[
        "rpe-high",
        "rpe-low",
        "soreness-high",
        "sleep-low",
        "energy-high",
        "stress-low",
        "energy-text",
        "bad-date",
        "unknown-field",
        "empty",
        "date-only",
    ],
)
def test_invalid_bodies_are_422_and_write_nothing(client, metrics, body):
    assert client.post(ROUTE, json=body, headers=AUTH).status_code == 422
    assert metrics.get_daily_metrics(DAY) is None


@pytest.mark.parametrize(("field", "value"), [("rpe_yesterday", 1), ("rpe_yesterday", 10), ("stress", 5)])
def test_bounds_are_inclusive(client, field, value):
    assert _post(client, date=DAY, **{field: value}).status_code == 200


def test_missing_date_defaults_to_today_in_apex_timezone(client, metrics):
    response = _post(client, energy=3)

    today = datetime.now(ZoneInfo("Pacific/Auckland")).date().isoformat()
    assert response.json()["date"] == today
    assert metrics.get_daily_metrics(today)["subjective_energy"] == 3


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}], ids=["none", "wrong"])
def test_request_without_a_valid_key_is_401(client, metrics, headers):
    assert client.post(ROUTE, json={"date": DAY, "energy": 3}, headers=headers).status_code == 401
    assert metrics.get_daily_metrics(DAY) is None
