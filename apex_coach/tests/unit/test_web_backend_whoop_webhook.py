"""F21.4: POST /webhooks/whoop. Signatures are computed over the raw bytes."""

import base64
import hashlib
import hmac
import importlib
import json
import os
import time
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from apex_coach.adapters.whoop_adapter import WHOOP_BASE_URL
from apex_coach.db.engine import create_engine
from apex_coach.db.schema import daily_metrics, metadata, whoop_webhook_events
from apex_coach.db.webhook_repository import WebhookEventRepository

SECRET = "client-secret"
EVENT = {"user_id": 1, "id": "abc-uuid", "type": "workout.updated", "trace_id": "trace-1"}


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
        "WHOOP_CLIENT_ID": "client-id",
        "WHOOP_CLIENT_SECRET": SECRET,
        **overrides,
    }
    with patch.dict(os.environ, env, clear=True):
        import web.backend.main as main_module

        importlib.reload(main_module)
    return TestClient(main_module.app)


@pytest.fixture
def client(engine):
    return _client(engine)


def _sign(body: bytes, timestamp: str, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _now_ms(offset_s: int = 0) -> str:
    return str(int((time.time() + offset_s) * 1000))


def _post(client, body: bytes, timestamp=None, signature=None):
    timestamp = timestamp or _now_ms()
    return client.post(
        "/webhooks/whoop",
        content=body,
        headers={
            "X-WHOOP-Signature-Timestamp": timestamp,
            "X-WHOOP-Signature": signature or _sign(body, timestamp),
        },
    )


def _events(engine):
    with engine.connect() as conn:
        return conn.execute(sa.select(whoop_webhook_events)).all()


BODY = json.dumps(EVENT).encode()


def test_valid_signature_is_200_and_recorded_without_an_api_key(client, engine):
    assert _post(client, BODY).status_code == 200

    row = _events(engine)[0]
    assert (row.trace_id, row.type, row.record_id, row.status) == (
        "trace-1",
        "workout.updated",
        "abc-uuid",
        "ignored",
    )


def test_tampered_body_is_401(client, engine):
    timestamp = _now_ms()
    signature = _sign(BODY, timestamp)

    assert _post(client, BODY + b" ", timestamp, signature).status_code == 401
    assert _events(engine) == []


def test_signature_is_over_raw_bytes_not_parsed_json(client):
    timestamp = _now_ms()
    signature = _sign(json.dumps(EVENT, indent=2).encode(), timestamp)

    assert _post(client, BODY, timestamp, signature).status_code == 401


def test_wrong_secret_is_401(client):
    timestamp = _now_ms()

    assert _post(client, BODY, timestamp, _sign(BODY, timestamp, "other")).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-WHOOP-Signature": "x"},
        {"X-WHOOP-Signature-Timestamp": "1"},
        {"X-WHOOP-Signature": "x", "X-WHOOP-Signature-Timestamp": "not-a-number"},
    ],
)
def test_missing_or_malformed_headers_are_401(client, headers):
    assert client.post("/webhooks/whoop", content=BODY, headers=headers).status_code == 401


@pytest.mark.parametrize("offset_s", [-360, 360])
def test_timestamp_beyond_the_tolerance_is_401(client, offset_s):
    assert _post(client, BODY, _now_ms(offset_s)).status_code == 401


@pytest.mark.parametrize("offset_s", [-240, 240])
def test_timestamp_within_the_tolerance_is_accepted(client, offset_s):
    assert _post(client, BODY, _now_ms(offset_s)).status_code == 200


@pytest.mark.parametrize(
    "body", [b"not json", b"[]", b'{"id": "x"}'], ids=["not-json", "not-object", "missing-fields"]
)
def test_signed_but_malformed_body_is_400(client, body):
    assert _post(client, body).status_code == 400


def test_missing_secret_fails_closed(engine):
    client = _client(engine, WHOOP_CLIENT_SECRET="")

    assert _post(client, BODY).status_code == 503


def test_same_trace_id_twice_processes_once(client, httpx_mock, engine):
    expires = "2099-01-01T00:00:00+00:00"
    from apex_coach.db.token_repository import TokenRepository

    TokenRepository(engine, "test-key").save_token("WHOOP", "a", "r", expires, "s")
    sleep_url = f"{WHOOP_BASE_URL}/developer/v2/activity/sleep/abc-uuid"
    httpx_mock.add_response(
        url=sleep_url,
        json={
            "id": "abc-uuid",
            "cycle_id": 1,
            "start": "2026-06-22T21:00:00Z",
            "end": "2026-06-23T05:00:00Z",
            "nap": True,
            "score_state": "SCORED",
        },
    )
    body = json.dumps({**EVENT, "type": "sleep.updated"}).encode()

    assert _post(client, body).status_code == 200
    assert _post(client, body).status_code == 200

    assert len(_events(engine)) == 1
    assert len(httpx_mock.get_requests()) == 1


def test_whoop_failure_still_answers_200_and_keeps_the_event_for_later(client, engine):
    body = json.dumps({**EVENT, "type": "sleep.updated"}).encode()

    assert _post(client, body).status_code == 200

    row = _events(engine)[0]
    assert row.status == "error"
    assert "connect-whoop" in row.error
    assert row.processed_at is None
    with engine.connect() as conn:
        assert conn.execute(sa.select(daily_metrics)).all() == []


def test_a_failed_event_is_processed_again_when_redelivered(engine):
    repo = WebhookEventRepository(engine)

    assert repo.record_received("t", "sleep.updated", "id") is True
    repo.mark("t", "error", "boom")
    assert repo.record_received("t", "sleep.updated", "id") is True
    repo.mark("t", "pending")
    assert repo.record_received("t", "sleep.updated", "id") is True
    repo.mark("t", "processed")
    assert repo.record_received("t", "sleep.updated", "id") is False
    assert repo.get("t")["processed_at"] is not None
