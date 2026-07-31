from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

from apex_coach.adapters.errors import AdapterMalformedResponseError, AdapterTimeoutError
from apex_coach.adapters.strava_adapter import (
    PER_PAGE,
    RATE_LIMIT_MAX_RETRIES,
    RealStravaAdapter,
    StravaActivityNotFoundError,
    StravaRateLimitError,
    StravaReauthorizationRequiredError,
    StravaScopeError,
    build_authorization_url,
    exchange_code_for_tokens,
    refresh_tokens,
    run_authorization_flow,
)
from apex_coach.db.engine import create_engine
from apex_coach.db.schema import metadata
from apex_coach.db.token_repository import TokenRepository

ENCRYPTION_KEY = "test-passphrase-not-for-production"


def _activity(activity_id: int, start_date: str = "2026-07-30T06:00:00Z") -> dict:
    return {
        "id": activity_id,
        "name": f"Run {activity_id}",
        "type": "Run",
        "start_date": start_date,
        "elapsed_time": 1800,
        "distance": 5000.0,
        "total_elevation_gain": 20.0,
        "average_speed": 2.78,
        "average_heartrate": 150.0,
        "max_heartrate": 165.0,
        "has_heartrate": True,
    }


STREAM_PAYLOAD = {
    "heartrate": {"data": [140.0, 145.0, 150.0], "series_type": "distance", "original_size": 3},
    "time": {"data": [0.0, 1.0, 2.0], "series_type": "distance", "original_size": 3},
    "distance": {"data": [0.0, 3.0, 6.0], "series_type": "distance", "original_size": 3},
}


@pytest.fixture
def token_repo():
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    repo = TokenRepository(engine, ENCRYPTION_KEY)
    repo.save_token(
        provider="STRAVA",
        access_token="valid-access-token",
        refresh_token="valid-refresh-token",
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        scope="read,activity:read_all",
    )
    return repo


@pytest.fixture
def sleeps():
    calls = []
    return calls, (lambda seconds: calls.append(seconds))


def _adapter(token_repo, sleep_fn):
    return RealStravaAdapter(token_repo, "client-id", "client-secret", sleep_fn=sleep_fn)


# -- OAuth flow functions -----------------------------------------------------


def test_build_authorization_url_has_no_pkce_params():
    url = build_authorization_url("cid", "https://example.com/callback", "state1")
    assert "response_type=code" in url
    assert "client_id=cid" in url
    assert "state=state1" in url
    assert "code_challenge" not in url


def test_exchange_code_for_tokens(httpx_mock):
    httpx_mock.add_response(
        url="https://www.strava.com/api/v3/oauth/token",
        json={
            "access_token": "a",
            "refresh_token": "r",
            "expires_at": 1234567890,
            "expires_in": 21600,
            "token_type": "Bearer",
        },
    )
    result = exchange_code_for_tokens("cid", "secret", "code123")
    assert result["access_token"] == "a"


def test_refresh_tokens(httpx_mock):
    httpx_mock.add_response(
        url="https://www.strava.com/api/v3/oauth/token",
        json={"access_token": "a2", "refresh_token": "r2", "expires_at": 1234567890, "expires_in": 21600},
    )
    result = refresh_tokens("cid", "secret", "old-refresh")
    assert result["access_token"] == "a2"


def test_run_authorization_flow_happy_path_pastes_code_and_state(httpx_mock):
    httpx_mock.add_response(
        url="https://www.strava.com/api/v3/oauth/token",
        json={"access_token": "a", "refresh_token": "r", "expires_at": 1234567890, "expires_in": 21600},
    )
    inputs = iter(["code123", "fixed-state"])
    with patch("apex_coach.adapters.strava_adapter.generate_state", return_value="fixed-state"):
        result = run_authorization_flow(
            "cid",
            "secret",
            "https://matna449.github.io/ApexCoach/callback.html",
            input_fn=lambda _: next(inputs),
        )
    assert result["access_token"] == "a"


def test_run_authorization_flow_state_mismatch_raises():
    inputs = iter(["code123", "wrong-state"])
    with patch("apex_coach.adapters.strava_adapter.generate_state", return_value="fixed-state"):
        with pytest.raises(StravaReauthorizationRequiredError):
            run_authorization_flow(
                "cid",
                "secret",
                "https://matna449.github.io/ApexCoach/callback.html",
                input_fn=lambda _: next(inputs),
            )


# -- get_new_activities — pagination ------------------------------------------


def test_get_new_activities_single_short_page(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(
        url="https://www.strava.com/api/v3/athlete/activities?after=0&per_page=30&page=1",
        json=[_activity(1), _activity(2)],
    )

    adapter = _adapter(token_repo, sleep_fn)
    activities = adapter.get_new_activities(0)

    assert [a.id for a in activities] == [1, 2]


def test_get_new_activities_paginates_across_full_pages(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    page1 = [_activity(i) for i in range(PER_PAGE)]
    page2 = [_activity(1000)]
    httpx_mock.add_response(
        url=f"https://www.strava.com/api/v3/athlete/activities?after=0&per_page={PER_PAGE}&page=1",
        json=page1,
    )
    httpx_mock.add_response(
        url=f"https://www.strava.com/api/v3/athlete/activities?after=0&per_page={PER_PAGE}&page=2",
        json=page2,
    )

    adapter = _adapter(token_repo, sleep_fn)
    activities = adapter.get_new_activities(0)

    assert len(activities) == PER_PAGE + 1
    assert activities[-1].id == 1000


def test_get_new_activities_empty_first_page_returns_empty(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(
        url="https://www.strava.com/api/v3/athlete/activities?after=0&per_page=30&page=1",
        json=[],
    )

    adapter = _adapter(token_repo, sleep_fn)
    assert adapter.get_new_activities(0) == []


def test_get_new_activities_raises_without_stored_token(httpx_mock):
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    empty_repo = TokenRepository(engine, ENCRYPTION_KEY)

    adapter = RealStravaAdapter(empty_repo, "cid", "secret")
    with pytest.raises(StravaReauthorizationRequiredError):
        adapter.get_new_activities(0)


def test_malformed_response_raises_adapter_malformed_response_error(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(
        url="https://www.strava.com/api/v3/athlete/activities?after=0&per_page=30&page=1",
        json=[{"id": "not-an-int"}],
    )

    adapter = _adapter(token_repo, sleep_fn)
    with pytest.raises(AdapterMalformedResponseError):
        adapter.get_new_activities(0)


# -- Token refresh — rotation --------------------------------------------------


def test_refreshes_and_stores_rotated_refresh_token(httpx_mock, sleeps):
    _, sleep_fn = sleeps
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    repo = TokenRepository(engine, ENCRYPTION_KEY)
    repo.save_token(
        provider="STRAVA",
        access_token="stale-token",
        refresh_token="refresh-me",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
        scope="read,activity:read_all",
    )

    future_expiry = int((datetime.now(timezone.utc) + timedelta(hours=6)).timestamp())
    httpx_mock.add_response(
        url="https://www.strava.com/api/v3/oauth/token",
        json={
            "access_token": "fresh-token",
            "refresh_token": "rotated-refresh",
            "expires_at": future_expiry,
            "expires_in": 21600,
        },
    )
    httpx_mock.add_response(
        url="https://www.strava.com/api/v3/athlete/activities?after=0&per_page=30&page=1",
        json=[],
    )

    adapter = RealStravaAdapter(repo, "cid", "secret", sleep_fn=sleep_fn)
    adapter.get_new_activities(0)

    stored = repo.get_token("STRAVA")
    assert stored["access_token"] == "fresh-token"
    assert stored["refresh_token"] == "rotated-refresh"


# -- Failure modes (§6.2) ------------------------------------------------------


def test_401_raises_reauthorization_required(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(
        url="https://www.strava.com/api/v3/athlete/activities?after=0&per_page=30&page=1",
        status_code=401,
    )

    adapter = _adapter(token_repo, sleep_fn)
    with pytest.raises(StravaReauthorizationRequiredError):
        adapter.get_new_activities(0)


def test_403_raises_scope_error(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(
        url="https://www.strava.com/api/v3/athlete/activities?after=0&per_page=30&page=1",
        status_code=403,
    )

    adapter = _adapter(token_repo, sleep_fn)
    with pytest.raises(StravaScopeError):
        adapter.get_new_activities(0)


def test_429_retries_then_succeeds(httpx_mock, token_repo, sleeps):
    calls, sleep_fn = sleeps
    httpx_mock.add_response(
        url="https://www.strava.com/api/v3/athlete/activities?after=0&per_page=30&page=1",
        status_code=429,
    )
    httpx_mock.add_response(
        url="https://www.strava.com/api/v3/athlete/activities?after=0&per_page=30&page=1",
        json=[],
    )

    adapter = _adapter(token_repo, sleep_fn)
    assert adapter.get_new_activities(0) == []
    assert calls == [900]


def test_429_exhausts_retries_and_raises(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    for _ in range(RATE_LIMIT_MAX_RETRIES + 1):
        httpx_mock.add_response(
            url="https://www.strava.com/api/v3/athlete/activities?after=0&per_page=30&page=1",
            status_code=429,
        )

    adapter = _adapter(token_repo, sleep_fn)
    with pytest.raises(StravaRateLimitError):
        adapter.get_new_activities(0)


def test_network_timeout_raises_adapter_timeout_error(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_exception(
        httpx.TimeoutException("timed out"),
        url="https://www.strava.com/api/v3/athlete/activities?after=0&per_page=30&page=1",
    )

    adapter = _adapter(token_repo, sleep_fn)
    with pytest.raises(AdapterTimeoutError):
        adapter.get_new_activities(0)


# -- get_activity_stream --------------------------------------------------------


def test_get_activity_stream_happy_path(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(
        url="https://www.strava.com/api/v3/activities/42/streams?keys=heartrate%2Ctime%2Cdistance&key_by_type=true&series_type=distance",
        json=STREAM_PAYLOAD,
    )

    adapter = _adapter(token_repo, sleep_fn)
    stream = adapter.get_activity_stream(42)

    assert stream is not None
    assert stream.heartrate.data == [140.0, 145.0, 150.0]


def test_get_activity_stream_404_returns_none(httpx_mock, token_repo, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(
        url="https://www.strava.com/api/v3/activities/42/streams?keys=heartrate%2Ctime%2Cdistance&key_by_type=true&series_type=distance",
        status_code=404,
    )

    adapter = _adapter(token_repo, sleep_fn)
    assert adapter.get_activity_stream(42) is None
