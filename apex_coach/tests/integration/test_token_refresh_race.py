"""F21 spec §5.1: WHOOP rotates refresh tokens, so concurrent refreshes must
collapse into one call."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import httpx
import pytest

from apex_coach.adapters.whoop_adapter import (
    WHOOP_TOKEN_URL,
    RealWhoopAdapter,
    WhoopReauthorizationRequiredError,
    WhoopServerError,
)
from apex_coach.db.engine import create_engine
from apex_coach.db.schema import metadata
from apex_coach.db.token_repository import REAUTH_REQUIRED, TokenRepository


def _iso(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def repo(request, tmp_path):
    """A file database on SQLite, because each thread needs its own connection."""
    url = (
        f"sqlite:///{tmp_path / 'race.db'}"
        if request.param == "sqlite"
        else request.getfixturevalue("postgres_url")
    )
    engine = create_engine(url)
    metadata.drop_all(engine)
    metadata.create_all(engine)
    repo = TokenRepository(engine, "test-key")
    repo.save_token("WHOOP", "old-access", "old-refresh", _iso(-10), "read:recovery")
    yield repo
    metadata.drop_all(engine)
    engine.dispose()


def _adapter(repo):
    return RealWhoopAdapter(repo, "client-id", "client-secret", http_client=httpx.Client())


def _refreshed_response():
    return {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}


def test_two_threads_refresh_once_and_both_get_the_new_token(repo, httpx_mock):
    httpx_mock.add_response(method="POST", url=WHOOP_TOKEN_URL, json=_refreshed_response())
    barrier = Barrier(2)

    def access_token():
        barrier.wait()
        return _adapter(repo)._access_token()

    with ThreadPoolExecutor(2) as pool:
        results = [f.result() for f in [pool.submit(access_token) for _ in range(2)]]

    assert results == ["new-access", "new-access"]
    assert len(httpx_mock.get_requests()) == 1
    assert repo.get_token("WHOOP")["refresh_token"] == "new-refresh"


def test_refresh_uses_the_stored_refresh_token(repo, httpx_mock):
    httpx_mock.add_response(method="POST", url=WHOOP_TOKEN_URL, json=_refreshed_response())

    _adapter(repo)._access_token()

    assert b"refresh_token=old-refresh" in httpx_mock.get_requests()[0].content


def test_a_fresh_token_never_contacts_whoop(repo, httpx_mock):
    repo.save_token("WHOOP", "fresh-access", "r", _iso(3600), "s")

    assert _adapter(repo)._access_token() == "fresh-access"
    assert httpx_mock.get_requests() == []


@pytest.mark.parametrize("status", [400, 401])
def test_rejected_refresh_marks_reauth_and_is_not_retried(repo, httpx_mock, status):
    httpx_mock.add_response(method="POST", url=WHOOP_TOKEN_URL, status_code=status)

    for _ in range(2):
        with pytest.raises(WhoopReauthorizationRequiredError):
            _adapter(repo)._access_token()

    assert repo.get_token("WHOOP")["sync_status"] == REAUTH_REQUIRED
    assert len(httpx_mock.get_requests()) == 1


def test_a_whoop_outage_keeps_the_token_usable(repo, httpx_mock):
    httpx_mock.add_response(method="POST", url=WHOOP_TOKEN_URL, status_code=500)

    with pytest.raises(WhoopServerError):
        _adapter(repo)._access_token()

    token = repo.get_token("WHOOP")
    assert token["sync_status"] is None
    assert token["refresh_token"] == "old-refresh"


def test_reconnecting_clears_reauth_required(repo, httpx_mock):
    httpx_mock.add_response(method="POST", url=WHOOP_TOKEN_URL, status_code=400)
    with pytest.raises(WhoopReauthorizationRequiredError):
        _adapter(repo)._access_token()

    repo.save_token("WHOOP", "a", "r", _iso(3600), "s")

    assert repo.get_token("WHOOP")["sync_status"] is None
