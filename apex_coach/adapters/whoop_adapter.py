"""WHOOP adapter Protocol + MockWhoopAdapter/RealWhoopAdapter (ADR-0011).

get_daily_payload() is the only public method — it combines all 3 WHOOP
endpoints into one WhoopDailyPayload. Per-endpoint calls are internal.
RealWhoopAdapter's OAuth flow, retry logic, and error classification are
documented in docs/adr/0018.
"""

import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx
from pydantic import ValidationError

from apex_coach.adapters.errors import (
    AdapterMalformedResponseError,
    AdapterTimeoutError,
    AdapterUnavailableError,
)
from apex_coach.adapters.oauth_pkce import (
    generate_pkce_pair,
    generate_state,
    wait_for_callback,
)
from apex_coach.models.pydantic_models import (
    WhoopCycle,
    WhoopDailyPayload,
    WhoopRecovery,
    WhoopSleep,
)

WHOOP_BASE_URL = "https://api.prod.whoop.com"
WHOOP_AUTH_URL = f"{WHOOP_BASE_URL}/oauth/oauth2/auth"
WHOOP_TOKEN_URL = f"{WHOOP_BASE_URL}/oauth/oauth2/token"
WHOOP_SCOPE = "read:recovery read:sleep read:strain read:body_measurement"

RATE_LIMIT_RETRY_DELAY_S = 60
RATE_LIMIT_MAX_RETRIES = 3
SERVER_ERROR_RETRY_DELAY_S = 30
PENDING_SCORE_RETRY_DELAY_S = 600


class WhoopReauthorizationRequiredError(AdapterUnavailableError):
    """401 with a failed refresh — athlete must re-run connect-whoop."""


class WhoopRateLimitError(AdapterUnavailableError):
    """429, retries exhausted."""


class WhoopServerError(AdapterUnavailableError):
    """500/503, retry exhausted."""


class WhoopPendingScoreError(AdapterUnavailableError):
    """score_state stayed PENDING_SCORE after the documented retry wait."""

# Mock payloads per API Contract §2.2-§2.4's documented examples.
MOCK_RECOVERY_PAYLOAD = {
    "cycle_id": 98234871,
    "created_at": "2026-06-23T06:14:22.000Z",
    "score_state": "SCORED",
    "score": {
        "recovery_score": 62.0,
        "resting_heart_rate": 48.0,
        "hrv_rmssd_milli": 71.4,
        "spo2_percentage": 96.2,
        "skin_temp_celsius": 34.1,
    },
}

MOCK_CYCLE_PAYLOAD = {
    "id": 102938471,
    "created_at": "2026-06-23T04:30:00.000Z",
    "score_state": "SCORED",
    "score": {
        "strain": 8.4,
        "kilojoule": 1842.0,
        "average_heart_rate": 72,
        "max_heart_rate": 164,
    },
}

MOCK_SLEEP_PAYLOAD = {
    "id": 84729301,
    "created_at": "2026-06-23T06:14:00.000Z",
    "score_state": "SCORED",
    "score": {
        "sleep_performance_percentage": 81.0,
        "stage_summary": {
            "total_in_bed_time_milli": 28200000,
            "total_awake_time_milli": 1620000,
        },
    },
}


class WhoopAdapterProtocol(Protocol):
    def get_daily_payload(self, date: str) -> WhoopDailyPayload: ...


class MockWhoopAdapter:
    """Deterministic WHOOP payload built from API Contract §2.2-§2.4 mock data."""

    def __init__(self, malformed: bool = False):
        self._malformed = malformed

    def get_daily_payload(self, date: str) -> WhoopDailyPayload:
        try:
            recovery_data = MOCK_RECOVERY_PAYLOAD
            if self._malformed:
                # CONTRACT RULE: a validation failure is treated the same as
                # an API error.
                recovery_data = {"cycle_id": "not-an-int", "created_at": "not-a-date"}

            return WhoopDailyPayload(
                date=date,
                recovery=WhoopRecovery(**recovery_data),
                cycle=WhoopCycle(**MOCK_CYCLE_PAYLOAD),
                sleep=WhoopSleep(**MOCK_SLEEP_PAYLOAD),
            )
        except ValidationError as e:
            raise AdapterMalformedResponseError(str(e)) from e


# -- OAuth 2.0 PKCE flow (API Contract §2.1) --------------------------------


def build_authorization_url(
    client_id: str, redirect_uri: str, state: str, code_challenge: str
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": WHOOP_SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{WHOOP_AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(
    client_id: str, client_secret: str, redirect_uri: str, code: str, code_verifier: str
) -> dict:
    response = httpx.post(
        WHOOP_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
    )
    response.raise_for_status()
    return response.json()


def refresh_tokens(client_id: str, client_secret: str, refresh_token: str) -> dict:
    response = httpx.post(
        WHOOP_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    response.raise_for_status()
    return response.json()


def run_authorization_flow(
    client_id: str, client_secret: str, redirect_uri: str, callback_timeout_seconds: int = 120
) -> dict:
    """The one-time browser handshake (API Contract §2.1 STEP 2-4). Blocks
    until the redirect arrives at redirect_uri (docs/adr/0018), or raises
    TimeoutError. Returns the raw token response (access_token,
    refresh_token, expires_in)."""
    parsed_redirect = urllib.parse.urlparse(redirect_uri)
    host = parsed_redirect.hostname
    port = parsed_redirect.port
    path = parsed_redirect.path or "/"

    code_verifier, code_challenge = generate_pkce_pair()
    state = generate_state()
    auth_url = build_authorization_url(client_id, redirect_uri, state, code_challenge)

    print(f"Open this URL to authorize WHOOP access:\n\n{auth_url}\n")
    result = wait_for_callback(host, port, path, timeout_seconds=callback_timeout_seconds)

    if result.error:
        raise WhoopReauthorizationRequiredError(f"authorization denied: {result.error}")
    if result.state != state:
        raise WhoopReauthorizationRequiredError("state mismatch — possible CSRF, aborting")
    if not result.code:
        raise WhoopReauthorizationRequiredError("no authorization code received")

    return exchange_code_for_tokens(client_id, client_secret, redirect_uri, result.code, code_verifier)


# -- RealWhoopAdapter (API Contract §2.2-§2.4, §6.1) -------------------------


class RealWhoopAdapter:
    """Drop-in replacement for MockWhoopAdapter behind WhoopAdapterProtocol.
    Refreshes tokens via token_repository, handles §6.1's failure modes."""

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
        self._client = http_client or httpx.Client(base_url=WHOOP_BASE_URL)

    def _access_token(self) -> str:
        # needs_refresh() raises a bare ValueError when no token has ever
        # been saved — fetch first so a never-connected athlete gets a
        # clear AdapterError instead of an unhandled exception.
        token = self._token_repo.get_token("WHOOP")
        if token is None:
            raise WhoopReauthorizationRequiredError(
                "no stored WHOOP token — run connect-whoop first"
            )

        if self._token_repo.needs_refresh("WHOOP"):
            try:
                response = refresh_tokens(
                    self._client_id, self._client_secret, token["refresh_token"]
                )
            except httpx.HTTPStatusError as e:
                raise WhoopReauthorizationRequiredError(
                    "token refresh failed — re-authorization required"
                ) from e

            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=response["expires_in"])
            ).isoformat()
            self._token_repo.save_token(
                provider="WHOOP",
                access_token=response["access_token"],
                refresh_token=response.get("refresh_token", token["refresh_token"]),
                expires_at=expires_at,
                scope=WHOOP_SCOPE,
            )
            token = self._token_repo.get_token("WHOOP")

        return token["access_token"]

    def _get(self, path: str) -> dict:
        """§6.1: 401 (handled by _access_token before this is called), 429
        (retry 60s x3), 500/503 (retry once after 30s), network timeout."""
        headers = {"Authorization": f"Bearer {self._access_token()}"}

        for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
            try:
                response = self._client.get(path, headers=headers)
            except httpx.TimeoutException as e:
                raise AdapterTimeoutError(f"WHOOP request timed out: {path}") from e
            except httpx.ConnectError as e:
                raise AdapterUnavailableError(f"WHOOP connection failed: {path}") from e

            if response.status_code == 401:
                raise WhoopReauthorizationRequiredError("401 from WHOOP — token invalid")
            if response.status_code == 429:
                if attempt < RATE_LIMIT_MAX_RETRIES:
                    self._sleep(RATE_LIMIT_RETRY_DELAY_S)
                    continue
                raise WhoopRateLimitError("WHOOP rate limit — retries exhausted")
            if response.status_code in (500, 503):
                if attempt == 0:
                    self._sleep(SERVER_ERROR_RETRY_DELAY_S)
                    continue
                raise WhoopServerError(f"WHOOP server error {response.status_code}")

            response.raise_for_status()
            return response.json()

        raise WhoopRateLimitError("WHOOP rate limit — retries exhausted")

    def _get_scored_record(self, path: str) -> dict:
        """score_state PENDING_SCORE: wait 10 min, retry once (§6.1)."""
        payload = self._get(path)
        record = payload["records"][0]
        if record["score_state"] == "PENDING_SCORE":
            self._sleep(PENDING_SCORE_RETRY_DELAY_S)
            payload = self._get(path)
            record = payload["records"][0]
            if record["score_state"] == "PENDING_SCORE":
                raise WhoopPendingScoreError("recovery still PENDING_SCORE after retry")
        return record

    def get_daily_payload(self, date: str) -> WhoopDailyPayload:
        # Validate each record immediately after fetching it, not after all
        # 3 calls — a malformed recovery response shouldn't cost 2 more
        # WHOOP API calls before the problem is discovered (§7.1: low-
        # frequency application, budget every call).
        try:
            recovery = WhoopRecovery(**self._get_scored_record("/v1/recovery?limit=1"))
            cycle = WhoopCycle(**self._get("/v1/cycle?limit=1")["records"][0])
            sleep = WhoopSleep(**self._get("/v1/activity/sleep?limit=1")["records"][0])
            return WhoopDailyPayload(date=date, recovery=recovery, cycle=cycle, sleep=sleep)
        except ValidationError as e:
            raise AdapterMalformedResponseError(str(e)) from e
