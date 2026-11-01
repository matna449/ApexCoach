"""F21.3: hosted WHOOP OAuth (F21 spec §5). Reloads web.backend.main under each
environment, the same way the other web backend tests do."""

import base64
import hashlib
import importlib
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from apex_coach.adapters.whoop_adapter import WHOOP_TOKEN_URL
from apex_coach.db.engine import create_engine
from apex_coach.db.schema import metadata, oauth_pending_states, oauth_tokens
from apex_coach.db.token_repository import TokenRepository

ENCRYPTION_KEY = "test-key"
ADMIN_KEY = "the-admin-key"
REDIRECT_URI = "https://app.example.com/auth/whoop/callback"
TOKEN_RESPONSE = {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600}


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    metadata.create_all(engine)
    return engine


def _client(engine, **overrides):
    env = {
        "APEX_ENCRYPTION_KEY": ENCRYPTION_KEY,
        "DATABASE_URL": str(engine.url),
        "APEX_API_KEY": "api-key",
        "APEX_ADMIN_KEY": ADMIN_KEY,
        "WHOOP_CLIENT_ID": "client-id",
        "WHOOP_CLIENT_SECRET": "client-secret",
        "WHOOP_REDIRECT_URI": REDIRECT_URI,
        **overrides,
    }
    with patch.dict(os.environ, env, clear=True):
        import web.backend.main as main_module

        importlib.reload(main_module)
    return TestClient(main_module.app, follow_redirects=False)


@pytest.fixture
def client(engine):
    return _client(engine)


def _start(client):
    response = client.get("/auth/whoop/start", params={"key": ADMIN_KEY})
    assert response.status_code == 302
    return parse_qs(urlparse(response.headers["location"]).query)


def _rows(engine, table):
    with engine.connect() as conn:
        return conn.execute(sa.select(table)).all()


def test_start_stores_state_and_encrypted_verifier_and_redirects_with_s256(client, engine):
    query = _start(client)

    row = _rows(engine, oauth_pending_states)[0]
    verifier = TokenRepository(engine, ENCRYPTION_KEY)._decrypt(row.code_verifier)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert row.state == query["state"][0]
    assert row.code_verifier != verifier
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [challenge.decode()]
    assert query["redirect_uri"] == [REDIRECT_URI]


@pytest.mark.parametrize("params", [{}, {"key": "wrong"}, {"key": "åäö"}], ids=["none", "wrong", "non-ascii"])
def test_start_rejects_a_bad_admin_key(client, engine, params):
    assert client.get("/auth/whoop/start", params=params).status_code == 401
    assert _rows(engine, oauth_pending_states) == []


def test_start_fails_closed_without_an_admin_key(engine):
    client = _client(engine, APEX_ADMIN_KEY="")

    assert client.get("/auth/whoop/start", params={"key": ""}).status_code == 503


def test_valid_callback_saves_the_token_encrypted(client, engine, httpx_mock):
    httpx_mock.add_response(method="POST", url=WHOOP_TOKEN_URL, json=TOKEN_RESPONSE)
    state = _start(client)["state"][0]

    response = client.get("/auth/whoop/callback", params={"code": "code-1", "state": state})

    assert response.status_code == 200
    assert "connected" in response.text
    row = _rows(engine, oauth_tokens)[0]
    assert (row.provider, row.sync_status) == ("WHOOP", None)
    assert "access-1" not in row.access_token and "refresh-1" not in row.refresh_token
    token = TokenRepository(engine, ENCRYPTION_KEY).get_token("WHOOP")
    assert (token["access_token"], token["refresh_token"]) == ("access-1", "refresh-1")
    body = httpx_mock.get_requests()[0].content
    assert b"code_verifier=" in body and b"code=code-1" in body


def test_callback_with_unknown_state_is_400_and_never_calls_whoop(client, engine, httpx_mock):
    response = client.get("/auth/whoop/callback", params={"code": "c", "state": "unknown"})

    assert response.status_code == 400
    assert httpx_mock.get_requests() == []
    assert _rows(engine, oauth_tokens) == []


def test_callback_with_expired_state_is_400(client, engine):
    state = _start(client)["state"][0]
    old = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    with engine.begin() as conn:
        conn.execute(oauth_pending_states.update().values(created_at=old))

    response = client.get("/auth/whoop/callback", params={"code": "c", "state": state})

    assert response.status_code == 400
    assert _rows(engine, oauth_tokens) == []


def test_state_is_single_use(client, httpx_mock):
    httpx_mock.add_response(method="POST", url=WHOOP_TOKEN_URL, json=TOKEN_RESPONSE)
    params = {"code": "c", "state": _start(client)["state"][0]}

    assert client.get("/auth/whoop/callback", params=params).status_code == 200
    assert client.get("/auth/whoop/callback", params=params).status_code == 400
    assert len(httpx_mock.get_requests()) == 1


def test_error_from_whoop_is_400_and_escaped_with_no_token_write(client, engine):
    response = client.get("/auth/whoop/callback", params={"error": "<script>denied</script>"})

    assert response.status_code == 400
    assert "<script>" not in response.text
    assert _rows(engine, oauth_tokens) == []


@pytest.mark.parametrize("params", [{"code": "c"}, {"state": "s"}, {}])
def test_callback_needs_code_and_state(client, params):
    assert client.get("/auth/whoop/callback", params=params).status_code == 400


def test_failed_token_exchange_is_502_with_no_token_write(client, engine, httpx_mock):
    httpx_mock.add_response(method="POST", url=WHOOP_TOKEN_URL, status_code=400)
    state = _start(client)["state"][0]

    response = client.get("/auth/whoop/callback", params={"code": "c", "state": state})

    assert response.status_code == 502
    assert _rows(engine, oauth_tokens) == []
