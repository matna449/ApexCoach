from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest
import sqlalchemy as sa

from apex_coach.adapters.errors import AdapterMalformedResponseError, AdapterTimeoutError
from apex_coach.adapters.whoop_adapter import (
    RATE_LIMIT_MAX_RETRIES,
    RealWhoopAdapter,
    WhoopPendingScoreError,
    WhoopRateLimitError,
    WhoopReauthorizationRequiredError,
    WhoopServerError,
    build_authorization_url,
    exchange_code_for_tokens,
    refresh_tokens,
    run_authorization_flow,
)
from apex_coach.db.engine import create_engine
from apex_coach.db.schema import metadata
from apex_coach.db.token_repository import TokenRepository

ENCRYPTION_KEY = "test-passphrase-not-for-production"

RECOVERY_PAYLOAD = {
    "records": [
        {
            "cycle_id": 1,
            "created_at": "2026-07-30T06:00:00.000Z",
            "score_state": "SCORED",
            "score": {
                "recovery_score": 62.0,
                "resting_heart_rate": 48.0,
                "hrv_rmssd_milli": 71.4,
            },
        }
    ]
}
CYCLE_PAYLOAD = {
    "records": [
        {
            "id": 1,
            "created_at": "2026-07-30T04:00:00.000Z",
            "score_state": "SCORED",
            "score": {
                "strain": 8.4,
                "kilojoule": 1842.0,
                "average_heart_rate": 72,
                "max_heart_rate": 164,
            },
        }
    ]
}
SLEEP_PAYLOAD = {
    "records": [
        {
            "id": 1,
            "created_at": "2026-07-30T06:00:00.000Z",
            "score_state": "SCORED",
            "score": {
                "sleep_performance_percentage": 81.0,
                "stage_summary": {
                    "total_in_bed_time_milli": 28200000,
                    "total_awake_time_milli": 1620000,
                },
            },
        }
    ]
}


@pytest.fixture
def token_repo():
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    repo = TokenRepository(engine, ENCRYPTION_KEY)
    repo.save_token(
        provider="WHOOP",
        access_token="valid-access-token",
        refresh_token="valid-refresh-token",
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        scope="read:recovery",
    )
    return repo


@pytest.fixture
def sleeps():
    calls = []
    return calls, (lambda seconds: calls.append(seconds))


def _adapter(token_repo, sleep_fn):
    return RealWhoopAdapter(token_repo, "client-id", "client-secret", sleep_fn=sleep_fn)


# -- OAuth flow functions -----------------------------------------------------


def test_build_authorization_url_includes_pkce_params():
    url = build_authorization_url("cid", "http://localhost:8080/callback", "state1", "chal1")
    assert "response_type=code" in url
    assert "client_id=cid" in url
    assert "code_challenge=chal1" in url
    assert "code_challenge_method=S256" in url
    assert "state=state1" in url


def test_exchange_code_for_tokens(httpx_mock):
    httpx_mock.add_response(
        url="https://api.prod.whoop.com/oauth/oauth2/token",
        json={"access_token": "a", "refresh_token": "r", "expires_in": 3600, "token_type": "Bearer"},
    )
    result = exchange_code_for_tokens("cid", "secret", "http://localhost:8080/callback", "code123", "verifier1")
    assert result["access_token"] == "a"


def test_refresh_tokens(httpx_mock):
    httpx_mock.add_response(
        url="https://api.prod.whoop.com/oauth/oauth2/token",
        json={"access_token": "a2", "refresh_token": "r2", "expires_in": 3600},
    )
    result = refresh_tokens("cid", "secret", "old-refresh")
    assert result["access_token"] == "a2"


def test_run_authorization_flow_happy_path_pastes_code_and_state(httpx_mock):
    httpx_mock.add_response(
        url="https://api.prod.whoop.com/oauth/oauth2/token",
        json={"access_token": "a", "refresh_token": "r", "expires_in": 3600},
    )
    inputs = iter(["code123", "fixed-state"])
    with patch("apex_coach.adapters.whoop_adapter.generate_state", return_value="fixed-state"):
        result = run_authorization_flow(
            "cid",
            "secret",
            "https://matna449.github.io/ApexCoach/callback.html",
            input_fn=lambda _: next(inputs),
        )
    assert result["access_token"] == "a"


def test_run_authorization_flow_state_mismatch_raises():
    inputs = iter(["code123", "wrong-state"])
    with patch("apex_coach.adapters.whoop_adapter.generate_state", return_value="fixed-state"):
        with pytest.raises(WhoopReauthorizationRequiredError):
            run_authorization_flow(
                "cid",
                "secret",
                "https://matna449.github.io/ApexCoach/callback.html",
                input_fn=lambda _: next(inputs),
            )


def test_run_authorization_flow_empty_code_raises():
    inputs = iter(["", "fixed-state"])
    with patch("apex_coach.adapters.whoop_adapter.generate_state", return_value="fixed-state"):
        with pytest.raises(WhoopReauthorizationRequiredError):
            run_authorization_flow(
                "cid",
                "secret",
                "https://matna449.github.io/ApexCoach/callback.html",
                input_fn=lambda _: next(inputs),
            )


# -- RealWhoopAdapter.get_daily_payload — happy path -------------------------


def test_get_daily_payload_happy_path(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/recovery?limit=1", json=RECOVERY_PAYLOAD)
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/cycle?limit=1", json=CYCLE_PAYLOAD)
    httpx_mock.add_response(
        url="https://api.prod.whoop.com/v2/activity/sleep?limit=1", json=SLEEP_PAYLOAD
    )

    adapter = _adapter(token_repo, sleep_fn)
    payload = adapter.get_daily_payload("2026-07-30")

    assert payload.whoop_recovery_pct == 62.0
    assert payload.whoop_strain == 8.4


def test_get_daily_payload_raises_without_stored_token(httpx_mock):
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    empty_repo = TokenRepository(engine, ENCRYPTION_KEY)

    adapter = RealWhoopAdapter(empty_repo, "cid", "secret")
    with pytest.raises(WhoopReauthorizationRequiredError):
        adapter.get_daily_payload("2026-07-30")


# -- Token refresh ------------------------------------------------------------


def test_refreshes_when_token_near_expiry(httpx_mock, sleeps):
    _, sleep_fn = sleeps
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    repo = TokenRepository(engine, ENCRYPTION_KEY)
    repo.save_token(
        provider="WHOOP",
        access_token="stale-token",
        refresh_token="refresh-me",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
        scope="read:recovery",
    )

    httpx_mock.add_response(
        url="https://api.prod.whoop.com/oauth/oauth2/token",
        json={"access_token": "fresh-token", "refresh_token": "new-refresh", "expires_in": 3600},
    )
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/recovery?limit=1", json=RECOVERY_PAYLOAD)
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/cycle?limit=1", json=CYCLE_PAYLOAD)
    httpx_mock.add_response(
        url="https://api.prod.whoop.com/v2/activity/sleep?limit=1", json=SLEEP_PAYLOAD
    )

    adapter = RealWhoopAdapter(repo, "cid", "secret", sleep_fn=sleep_fn)
    adapter.get_daily_payload("2026-07-30")

    assert repo.get_token("WHOOP")["access_token"] == "fresh-token"


# -- §6.1 Failure modes -------------------------------------------------------


def test_401_raises_reauthorization_required(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/recovery?limit=1", status_code=401)

    adapter = _adapter(token_repo, sleep_fn)
    with pytest.raises(WhoopReauthorizationRequiredError):
        adapter.get_daily_payload("2026-07-30")


def test_429_retries_then_succeeds(httpx_mock, token_repo, sleeps):
    calls, sleep_fn = sleeps
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/recovery?limit=1", status_code=429)
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/recovery?limit=1", json=RECOVERY_PAYLOAD)
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/cycle?limit=1", json=CYCLE_PAYLOAD)
    httpx_mock.add_response(
        url="https://api.prod.whoop.com/v2/activity/sleep?limit=1", json=SLEEP_PAYLOAD
    )

    adapter = _adapter(token_repo, sleep_fn)
    payload = adapter.get_daily_payload("2026-07-30")

    assert payload.whoop_recovery_pct == 62.0
    assert calls == [60]  # slept once, per RATE_LIMIT_RETRY_DELAY_S


def test_429_exhausts_retries_and_raises(httpx_mock, token_repo, sleeps):
    calls, sleep_fn = sleeps
    for _ in range(RATE_LIMIT_MAX_RETRIES + 1):
        httpx_mock.add_response(url="https://api.prod.whoop.com/v2/recovery?limit=1", status_code=429)

    adapter = _adapter(token_repo, sleep_fn)
    with pytest.raises(WhoopRateLimitError):
        adapter.get_daily_payload("2026-07-30")
    assert len(calls) == RATE_LIMIT_MAX_RETRIES


def test_503_retries_once_then_succeeds(httpx_mock, token_repo, sleeps):
    calls, sleep_fn = sleeps
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/recovery?limit=1", status_code=503)
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/recovery?limit=1", json=RECOVERY_PAYLOAD)
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/cycle?limit=1", json=CYCLE_PAYLOAD)
    httpx_mock.add_response(
        url="https://api.prod.whoop.com/v2/activity/sleep?limit=1", json=SLEEP_PAYLOAD
    )

    adapter = _adapter(token_repo, sleep_fn)
    adapter.get_daily_payload("2026-07-30")
    assert calls == [30]  # SERVER_ERROR_RETRY_DELAY_S


def test_500_twice_raises_server_error(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/recovery?limit=1", status_code=500)
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/recovery?limit=1", status_code=500)

    adapter = _adapter(token_repo, sleep_fn)
    with pytest.raises(WhoopServerError):
        adapter.get_daily_payload("2026-07-30")


def test_pending_score_retries_once_then_succeeds(httpx_mock, token_repo, sleeps):
    calls, sleep_fn = sleeps
    pending = {"records": [{**RECOVERY_PAYLOAD["records"][0], "score_state": "PENDING_SCORE", "score": None}]}
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/recovery?limit=1", json=pending)
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/recovery?limit=1", json=RECOVERY_PAYLOAD)
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/cycle?limit=1", json=CYCLE_PAYLOAD)
    httpx_mock.add_response(
        url="https://api.prod.whoop.com/v2/activity/sleep?limit=1", json=SLEEP_PAYLOAD
    )

    adapter = _adapter(token_repo, sleep_fn)
    payload = adapter.get_daily_payload("2026-07-30")

    assert payload.whoop_recovery_pct == 62.0
    assert calls == [600]  # PENDING_SCORE_RETRY_DELAY_S


def test_pending_score_still_pending_after_retry_raises(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    pending = {"records": [{**RECOVERY_PAYLOAD["records"][0], "score_state": "PENDING_SCORE", "score": None}]}
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/recovery?limit=1", json=pending)
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/recovery?limit=1", json=pending)

    adapter = _adapter(token_repo, sleep_fn)
    with pytest.raises(WhoopPendingScoreError):
        adapter.get_daily_payload("2026-07-30")


def test_network_timeout_raises_adapter_timeout_error(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_exception(httpx.TimeoutException("timed out"))

    adapter = _adapter(token_repo, sleep_fn)
    with pytest.raises(AdapterTimeoutError):
        adapter.get_daily_payload("2026-07-30")


def test_malformed_response_raises_adapter_malformed_response_error(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    bad_payload = {"records": [{"cycle_id": "not-an-int", "created_at": "bad", "score_state": "SCORED"}]}
    httpx_mock.add_response(url="https://api.prod.whoop.com/v2/recovery?limit=1", json=bad_payload)

    adapter = _adapter(token_repo, sleep_fn)
    with pytest.raises(AdapterMalformedResponseError):
        adapter.get_daily_payload("2026-07-30")
