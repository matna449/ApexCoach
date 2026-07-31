"""Strava adapter Protocol + MockStravaAdapter/RealStravaAdapter (API
Contract §3.2, §3.3).

get_activity_stream() (§3.3) added in F06.1 — see docs/adr/0014 for why
this ticket builds it rather than deferring it further.
RealStravaAdapter's OAuth flow, pagination, and error classification are
documented in docs/adr/0019.
"""

import time
import urllib.parse
from datetime import datetime, timezone
from typing import Protocol

import httpx
from pydantic import ValidationError

from apex_coach.adapters.errors import (
    AdapterMalformedResponseError,
    AdapterTimeoutError,
    AdapterUnavailableError,
)
from apex_coach.adapters.oauth_pkce import generate_state
from apex_coach.models.pydantic_models import StravaActivity, StravaStream

STRAVA_BASE_URL = "https://www.strava.com/api/v3"
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = f"{STRAVA_BASE_URL}/oauth/token"
STRAVA_SCOPE = "read,activity:read_all"

PER_PAGE = 30
RATE_LIMIT_RETRY_DELAY_S = 900
RATE_LIMIT_MAX_RETRIES = 3


class StravaReauthorizationRequiredError(AdapterUnavailableError):
    """401, or a failed token refresh — athlete must re-run connect-strava."""


class StravaScopeError(AdapterUnavailableError):
    """403 — token lacks activity:read_all. Athlete must re-authorise."""


class StravaActivityNotFoundError(AdapterUnavailableError):
    """404 — activity was deleted or made private on Strava's side."""


class StravaRateLimitError(AdapterUnavailableError):
    """429, retries exhausted."""

# Mock payload per API Contract §3.2's documented example.
MOCK_ACTIVITY_PAYLOAD = {
    "id": 12748392017,
    "name": "Tuesday Threshold - Track Session",
    "type": "Run",
    "start_date": "2026-06-23T06:30:00Z",
    "elapsed_time": 3247,
    "distance": 9843.2,
    "total_elevation_gain": 84.0,
    "average_speed": 3.173,
    "average_heartrate": 161.4,
    "max_heartrate": 178.0,
    "has_heartrate": True,
    "splits_metric": [
        {
            "split": 1,
            "distance": 1000.5,
            "elapsed_time": 272,
            "elevation_difference": 3.2,
            "average_speed": 3.731,
            "average_heartrate": 154.2,
            "average_grade_adjusted_speed": 3.612,
        }
    ],
}


def _generate_mock_hr_stream(duration_s: int) -> list[int]:
    """Deterministic synthetic HR profile: 10-min warm-up ramp, then a
    steady Threshold-zone effort with a small oscillation. Not randomised —
    tests need reproducible values."""
    hr = []
    for t in range(duration_s):
        if t < 600:
            hr.append(round(110 + (165 - 110) * (t / 600)))
        else:
            hr.append(165 + (3 if t % 20 < 10 else -3))
    return hr


_STREAM_DURATION = MOCK_ACTIVITY_PAYLOAD["elapsed_time"]
_STREAM_DISTANCE_PER_SEC = MOCK_ACTIVITY_PAYLOAD["distance"] / _STREAM_DURATION

MOCK_STREAM_PAYLOAD = {
    "heartrate": {
        "data": _generate_mock_hr_stream(_STREAM_DURATION),
        "series_type": "distance",
        "original_size": _STREAM_DURATION,
        "resolution": "high",
    },
    "time": {
        "data": list(range(_STREAM_DURATION)),
        "series_type": "distance",
        "original_size": _STREAM_DURATION,
    },
    "distance": {
        "data": [i * _STREAM_DISTANCE_PER_SEC for i in range(_STREAM_DURATION)],
        "series_type": "distance",
        "original_size": _STREAM_DURATION,
    },
}


class StravaAdapterProtocol(Protocol):
    def get_new_activities(self, since_ts: int) -> list[StravaActivity]: ...
    def get_activity_stream(self, activity_id: int) -> StravaStream | None: ...


class MockStravaAdapter:
    """Deterministic Strava activity list built from API Contract §3.2 mock data."""

    def __init__(self, malformed: bool = False):
        self._malformed = malformed

    def get_new_activities(self, since_ts: int) -> list[StravaActivity]:
        try:
            payload = MOCK_ACTIVITY_PAYLOAD
            if self._malformed:
                # CONTRACT RULE: a validation failure is treated the same as
                # an API error.
                payload = {"id": "not-an-int", "name": "bad activity"}

            activity = StravaActivity(**payload)
        except ValidationError as e:
            raise AdapterMalformedResponseError(str(e)) from e

        # Mirrors the real after={since_ts} query param (§3.2) — activities
        # at or before since_ts are already synced, not "new".
        if activity.start_date.timestamp() <= since_ts:
            return []
        return [activity]

    def get_activity_stream(self, activity_id: int) -> StravaStream | None:
        if activity_id != MOCK_ACTIVITY_PAYLOAD["id"]:
            return None

        try:
            return StravaStream(**MOCK_STREAM_PAYLOAD)
        except ValidationError as e:
            raise AdapterMalformedResponseError(str(e)) from e


# -- OAuth 2.0 Authorization Code flow, no PKCE (API Contract §3.1) --------


def build_authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": STRAVA_SCOPE,
        "state": state,
    }
    return f"{STRAVA_AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(client_id: str, client_secret: str, code: str) -> dict:
    response = httpx.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
    )
    response.raise_for_status()
    return response.json()


def refresh_tokens(client_id: str, client_secret: str, refresh_token: str) -> dict:
    response = httpx.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    response.raise_for_status()
    return response.json()


def run_authorization_flow(
    client_id: str, client_secret: str, redirect_uri: str, input_fn=input
) -> dict:
    """The one-time browser handshake (API Contract §3.1 STEP 2-4). Strava
    whitelists localhost/127.0.0.1 redirects, but redirect_uri points at the
    same hosted callback landing page WHOOP uses (docs/adr/0019), for
    consistency — the athlete pastes the code/state it displays back here.
    No PKCE: Strava's flow doesn't support it. Returns the raw token
    response (access_token, refresh_token, expires_at, expires_in)."""
    state = generate_state()
    auth_url = build_authorization_url(client_id, redirect_uri, state)

    print(f"Open this URL to authorize Strava access:\n\n{auth_url}\n")
    print("After approving, paste the code and state shown on the callback page below.\n")

    code = input_fn("Authorization code: ").strip()
    returned_state = input_fn("State: ").strip()

    if returned_state != state:
        raise StravaReauthorizationRequiredError("state mismatch — possible CSRF, aborting")
    if not code:
        raise StravaReauthorizationRequiredError("no authorization code received")

    return exchange_code_for_tokens(client_id, client_secret, code)


# -- RealStravaAdapter (API Contract §3.2, §3.3, §6.2) ----------------------


class RealStravaAdapter:
    """Drop-in replacement for MockStravaAdapter behind StravaAdapterProtocol.
    Refreshes tokens via token_repository, handles §6.2's failure modes."""

    def __init__(
        self,
        token_repo,
        client_id: str,
        client_secret: str,
        sleep_fn=time.sleep,
        http_client: httpx.Client | None = None,
    ):
        self._token_repo = token_repo
        self._client_id = client_id
        self._client_secret = client_secret
        self._sleep = sleep_fn
        self._client = http_client or httpx.Client(base_url=STRAVA_BASE_URL)

    def _access_token(self) -> str:
        token = self._token_repo.get_token("STRAVA")
        if token is None:
            raise StravaReauthorizationRequiredError(
                "no stored Strava token — run connect-strava first"
            )

        if self._token_repo.needs_refresh("STRAVA"):
            try:
                response = refresh_tokens(
                    self._client_id, self._client_secret, token["refresh_token"]
                )
            except httpx.HTTPStatusError as e:
                raise StravaReauthorizationRequiredError(
                    "token refresh failed — re-authorization required"
                ) from e

            expires_at = datetime.fromtimestamp(
                response["expires_at"], tz=timezone.utc
            ).isoformat()
            self._token_repo.save_token(
                provider="STRAVA",
                access_token=response["access_token"],
                # Strava rotates refresh tokens on every refresh (API
                # Contract §3.1 CRITICAL note) — never fall back to the old
                # one; a missing refresh_token here means Strava broke its
                # documented contract and should fail loudly, not silently.
                refresh_token=response["refresh_token"],
                expires_at=expires_at,
                scope=STRAVA_SCOPE,
            )
            token = self._token_repo.get_token("STRAVA")

        return token["access_token"]

    def _get(self, path: str, params: dict | None = None):
        """§6.2: 401 (re-auth), 403 (scope), 404 (not found — caller
        decides what that means), 429 (retry 15min x3), network timeout."""
        headers = {"Authorization": f"Bearer {self._access_token()}"}

        for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
            try:
                response = self._client.get(path, headers=headers, params=params)
            except httpx.TimeoutException as e:
                raise AdapterTimeoutError(f"Strava request timed out: {path}") from e
            except httpx.ConnectError as e:
                raise AdapterUnavailableError(f"Strava connection failed: {path}") from e

            if response.status_code == 401:
                raise StravaReauthorizationRequiredError("401 from Strava — token invalid")
            if response.status_code == 403:
                raise StravaScopeError(
                    "403 from Strava — insufficient scope, re-authorise with activity:read_all"
                )
            if response.status_code == 404:
                raise StravaActivityNotFoundError(f"404 from Strava: {path}")
            if response.status_code == 429:
                if attempt < RATE_LIMIT_MAX_RETRIES:
                    self._sleep(RATE_LIMIT_RETRY_DELAY_S)
                    continue
                raise StravaRateLimitError("Strava rate limit — retries exhausted")

            response.raise_for_status()
            return response.json()

        raise StravaRateLimitError("Strava rate limit — retries exhausted")

    def get_new_activities(self, since_ts: int) -> list[StravaActivity]:
        # Paginate until a short page signals the end (§7.2: after= already
        # limits us to genuinely new activities, so a short page — not
        # necessarily empty — is the correct stop condition).
        activities: list[StravaActivity] = []
        page = 1
        try:
            while True:
                records = self._get(
                    "/athlete/activities",
                    params={"after": since_ts, "per_page": PER_PAGE, "page": page},
                )
                if not records:
                    break
                activities.extend(StravaActivity(**r) for r in records)
                if len(records) < PER_PAGE:
                    break
                page += 1
        except ValidationError as e:
            raise AdapterMalformedResponseError(str(e)) from e
        return activities

    def get_activity_stream(self, activity_id: int) -> StravaStream | None:
        try:
            payload = self._get(
                f"/activities/{activity_id}/streams",
                params={
                    "keys": "heartrate,time,distance",
                    "key_by_type": "true",
                    "series_type": "distance",
                },
            )
        except StravaActivityNotFoundError:
            return None

        try:
            return StravaStream(**payload)
        except ValidationError as e:
            raise AdapterMalformedResponseError(str(e)) from e
