"""F21.5: GET /api/cron/whoop-reconcile and the backfill after connecting."""

import importlib
import os
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from apex_coach.adapters.whoop_adapter import WHOOP_BASE_URL, WHOOP_TOKEN_URL
from apex_coach.db.engine import create_engine
from apex_coach.db.schema import metadata, oauth_pending_states
from apex_coach.db.token_repository import TokenRepository
from apex_coach.db.webhook_repository import PENDING, WebhookEventRepository

CRON = "/api/cron/whoop-reconcile"
AUTH = {"Authorization": "Bearer cron-secret"}
EMPTY = {"records": [], "next_token": None}
ANY_COLLECTION = re.compile(re.escape(f"{WHOOP_BASE_URL}/developer/v2/") + r"(activity/sleep|recovery|cycle)\?.*")


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    metadata.create_all(engine)
    return engine


def _client(engine, **overrides):
    env = {
        "APEX_ENCRYPTION_KEY": "test-key",
        "DATABASE_URL": str(engine.url),
        "APEX_API_KEY": "api-key",
        "APEX_ADMIN_KEY": "admin",
        "CRON_SECRET": "cron-secret",
        "WHOOP_CLIENT_ID": "client-id",
        "WHOOP_CLIENT_SECRET": "client-secret",
        **overrides,
    }
    with patch.dict(os.environ, env, clear=True):
        import web.backend.main as main_module

        importlib.reload(main_module)
    return TestClient(main_module.app, follow_redirects=False)


@pytest.fixture
def client(engine):
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    TokenRepository(engine, "test-key").save_token("WHOOP", "a", "r", expires, "s")
    return _client(engine)


def _mock_whoop(httpx_mock):
    httpx_mock.add_response(url=ANY_COLLECTION, json=EMPTY, is_reusable=True, is_optional=True)


def _window_days(httpx_mock):
    start = parse_qs(urlparse(str(httpx_mock.get_requests()[0].url)).query)["start"][0]
    return (datetime.now(timezone.utc).date() - datetime.fromisoformat(start).date()).days


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "cron-secret"}],
    ids=["none", "wrong", "no-scheme"],
)
def test_call_without_the_cron_secret_is_401(client, headers, httpx_mock):
    assert client.get(CRON, headers=headers).status_code == 401
    assert httpx_mock.get_requests() == []


def test_api_key_is_not_a_cron_secret(client):
    assert client.get(CRON, headers={"Authorization": "Bearer api-key"}).status_code == 401


def test_missing_cron_secret_fails_closed(engine):
    client = _client(engine, CRON_SECRET="")

    assert client.get(CRON, headers={"Authorization": "Bearer "}).status_code == 503


def test_returns_counts(client, httpx_mock):
    _mock_whoop(httpx_mock)

    response = client.get(CRON, headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {
        "sleeps": 0,
        "recoveries": 0,
        "cycles": 0,
        "events_reprocessed": 0,
        "pending_states_purged": 0,
    }


@pytest.mark.parametrize(("days", "expected"), [(30, 30), (31, 30), (500, 30)])
def test_days_is_capped_at_30(client, httpx_mock, days, expected):
    _mock_whoop(httpx_mock)

    assert client.get(CRON, params={"days": days}, headers=AUTH).status_code == 200
    assert expected <= _window_days(httpx_mock) <= expected + 1


@pytest.mark.parametrize("days", [0, -1])
def test_days_must_be_positive(client, days):
    assert client.get(CRON, params={"days": days}, headers=AUTH).status_code == 422


def test_purges_expired_pending_states_and_keeps_fresh_ones(client, engine, httpx_mock):
    _mock_whoop(httpx_mock)
    repo = TokenRepository(engine, "test-key")
    repo.save_pending_state("fresh", "v")
    repo.save_pending_state("old", "v")
    old = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    with engine.begin() as conn:
        conn.execute(
            oauth_pending_states.update()
            .where(oauth_pending_states.c.state == "old")
            .values(created_at=old)
        )

    response = client.get(CRON, headers=AUTH)

    assert response.json()["pending_states_purged"] == 1
    with engine.connect() as conn:
        states = conn.execute(sa.select(oauth_pending_states.c.state)).scalars().all()
    assert states == ["fresh"]


def test_reprocesses_stuck_events(client, engine, httpx_mock):
    _mock_whoop(httpx_mock)
    events = WebhookEventRepository(engine)
    events.record_received("stuck", "workout.updated", "id")
    events.mark("stuck", PENDING)
    events.record_received("done", "workout.updated", "id")
    events.mark("done", "processed")

    response = client.get(CRON, headers=AUTH)

    assert response.json()["events_reprocessed"] == 1
    assert events.get("stuck")["status"] == "ignored"


def test_a_still_failing_event_stays_unfinished_and_the_run_succeeds(client, engine, httpx_mock):
    _mock_whoop(httpx_mock)
    httpx_mock.add_response(
        url=f"{WHOOP_BASE_URL}/developer/v2/activity/sleep/bad", status_code=500
    )
    events = WebhookEventRepository(engine)
    events.record_received("stuck", "sleep.updated", "bad")

    response = client.get(CRON, headers=AUTH)

    assert response.status_code == 200
    assert events.get("stuck")["status"] == "error"


def test_whoop_failure_is_502(client, httpx_mock):
    httpx_mock.add_response(url=ANY_COLLECTION, status_code=500)

    assert client.get(CRON, headers=AUTH).status_code == 502


def _connect(client):
    response = client.get("/auth/whoop/start", params={"key": "admin"})
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    return client.get("/auth/whoop/callback", params={"code": "c", "state": state})


def test_oauth_callback_backfills_30_days(engine, httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url=WHOOP_TOKEN_URL,
        json={"access_token": "a", "refresh_token": "r", "expires_in": 3600},
    )
    _mock_whoop(httpx_mock)

    assert _connect(_client(engine)).status_code == 200

    gets = [r for r in httpx_mock.get_requests() if r.method == "GET"]
    assert len(gets) == 3
    start = parse_qs(urlparse(str(gets[0].url)).query)["start"][0]
    age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(start).date()).days
    assert 30 <= age <= 31


def test_failed_backfill_still_connects(engine, httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url=WHOOP_TOKEN_URL,
        json={"access_token": "a", "refresh_token": "r", "expires_in": 3600},
    )
    httpx_mock.add_response(url=ANY_COLLECTION, status_code=500)

    response = _connect(_client(engine))

    assert response.status_code == 200
    assert TokenRepository(engine, "test-key").get_token("WHOOP")["access_token"] == "a"
