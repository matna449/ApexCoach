"""F21.6: GET /api/health/daily through the real app and repositories."""

import importlib
import os
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.schema import metadata
from apex_coach.db.token_repository import REAUTH_REQUIRED, TokenRepository
from apex_coach.db.webhook_repository import WebhookEventRepository
from apex_coach.db import schema

ROUTE = "/api/health/daily"
AUTH = {"Authorization": "Bearer api-key"}
TZ = ZoneInfo("Europe/Stockholm")


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
    }
    with patch.dict(os.environ, env, clear=True):
        import web.backend.main as main_module

        importlib.reload(main_module)
    return TestClient(main_module.app)


def _days_ago(n):
    return (datetime.now(TZ).date() - timedelta(days=n)).isoformat()


def _save_token(engine):
    TokenRepository(engine, "test-key").save_token(
        "WHOOP", "a", "r", "2099-01-01T00:00:00+00:00", "s"
    )


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}], ids=["none", "wrong"])
def test_request_without_a_valid_key_is_401(client, headers):
    assert client.get(ROUTE, headers=headers).status_code == 401


@pytest.mark.parametrize(("days", "status"), [(0, 422), (91, 422), (1, 200), (90, 200)])
def test_days_bounds_are_enforced(client, days, status):
    assert client.get(ROUTE, params={"days": days}, headers=AUTH).status_code == status


def test_defaults_to_14_days_and_reads_older_rows_for_the_averages(client, metrics):
    for n in range(1, 45):
        metrics.upsert_daily_metrics(_days_ago(n), whoop_hrv_ms=60.0)

    days = client.get(ROUTE, headers=AUTH).json()["days"]

    assert len(days) == 14
    oldest = days[-1]
    assert oldest["date"] == _days_ago(13)
    assert oldest["hrv_30d_avg"] == 60.0


def test_subjective_answers_written_by_the_agent_come_back(client):
    response = client.post(
        "/api/health/subjective", json={"energy": 5, "pain": "knee"}, headers=AUTH
    )
    assert response.status_code == 200

    today = client.get(ROUTE, params={"days": 1}, headers=AUTH).json()["days"][0]

    assert today["subjective"]["energy"] == 5
    assert today["subjective"]["pain"] == "knee"


def test_no_whoop_connection_reports_reauth_required(client):
    assert client.get(ROUTE, headers=AUTH).json()["sync"]["status"] == "REAUTH_REQUIRED"


def test_rejected_refresh_token_reports_reauth_required(client, engine):
    _save_token(engine)
    with engine.begin() as conn:
        conn.execute(schema.oauth_tokens.update().values(sync_status=REAUTH_REQUIRED))

    assert client.get(ROUTE, headers=AUTH).json()["sync"]["status"] == "REAUTH_REQUIRED"


def test_connected_with_no_synced_data_reports_stale(client, engine):
    _save_token(engine)

    assert client.get(ROUTE, headers=AUTH).json()["sync"]["status"] == "STALE"


def test_recent_sync_reports_ok(client, engine, metrics):
    _save_token(engine)
    now = datetime.now(TZ)
    metrics.upsert_daily_metrics(
        now.date().isoformat(), whoop_hrv_ms=60.0, whoop_synced_at=now.isoformat()
    )

    assert client.get(ROUTE, headers=AUTH).json()["sync"]["status"] == "OK"


def test_pending_events_counts_unfinished_ones(client, engine):
    events = WebhookEventRepository(engine)
    events.record_received("a", "sleep.updated", "1")
    events.record_received("b", "sleep.updated", "2")
    events.mark("b", "processed")

    assert client.get(ROUTE, headers=AUTH).json()["sync"]["pending_events"] == 1


def test_generated_at_is_local_time_with_an_offset(client):
    generated_at = datetime.fromisoformat(client.get(ROUTE, headers=AUTH).json()["generated_at"])

    assert generated_at.utcoffset() == datetime.now(TZ).utcoffset()
