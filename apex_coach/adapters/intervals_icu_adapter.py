"""intervals.icu adapter: MockIntervalsIcuAdapter/RealIntervalsIcuAdapter
implementing ActivitySyncAdapterProtocol (apex_coach/adapters/strava_adapter.py).

Auth is a static personal API key over HTTP Basic (username literal
"API_KEY", password = the key) — no OAuth handshake, no token refresh.
See docs/adr/0025 for the confirmed endpoint contract and activity-type
taxonomy this file implements against.
"""

import time
from datetime import datetime, timezone

import httpx
from pydantic import ValidationError

from apex_coach.adapters.errors import (
    AdapterMalformedResponseError,
    AdapterTimeoutError,
    AdapterUnavailableError,
)
from apex_coach.models.pydantic_models import Activity, ActivityStream, ActivityStreamSeries

INTERVALS_ICU_BASE_URL = "https://intervals.icu/api/v1"

RATE_LIMIT_RETRY_DELAY_S = 900
RATE_LIMIT_MAX_RETRIES = 3

ACTIVITY_FIELDS = (
    "id,name,type,start_date_local,distance,moving_time,total_elevation_gain,"
    "average_speed,average_heartrate,max_heartrate"
)

# docs/adr/0025 §5 — intervals.icu sport family -> ApexCoach canonical vocabulary.
_ACTIVITY_TYPE_MAP = {
    "Run": "Run",
    "VirtualRun": "Run",
    "TrackRun": "Run",
    "Ride": "Ride",
    "VirtualRide": "Ride",
    "MountainBikeRide": "Ride",
    "Swim": "Swim",
    "OpenWaterSwim": "Swim",
    "PoolSwim": "Swim",
    "WeightTraining": "WeightTraining",
    "Strength": "WeightTraining",
    "Crossfit": "WeightTraining",
    "Yoga": "Yoga",
    "Pilates": "Yoga",
    "Mobility": "Yoga",
}


class IntervalsIcuAuthError(AdapterUnavailableError):
    """401 — invalid or revoked API key."""


class IntervalsIcuActivityNotFoundError(AdapterUnavailableError):
    """404 — activity not found on intervals.icu's side."""


class IntervalsIcuRateLimitError(AdapterUnavailableError):
    """429, retries exhausted."""


class IntervalsIcuUnmappedActivityTypeError(AdapterMalformedResponseError):
    """intervals.icu returned a sport type with no canonical vocabulary
    mapping (docs/adr/0025 §5) — surfaced loudly rather than guessed at,
    since load_calculator.calculate_load_au() has no safe default bucket."""


def _map_activity_type(icu_type: str) -> str:
    mapped = _ACTIVITY_TYPE_MAP.get(icu_type)
    if mapped is None:
        raise IntervalsIcuUnmappedActivityTypeError(
            f"no canonical vocabulary mapping for intervals.icu type {icu_type!r}"
        )
    return mapped


def _as_utc_iso(local_iso: str) -> str:
    """intervals.icu's start_date_local carries no UTC offset. Treating it
    as UTC is a known simplification (true athlete-local offset isn't part
    of the confirmed API contract, docs/adr/0025) — deterministic and good
    enough for day-bucketing; F18.5's live run will surface if this needs
    correcting."""
    if local_iso.endswith("Z") or "+" in local_iso[10:]:
        return local_iso
    return f"{local_iso}Z"


def _record_to_activity(record: dict) -> Activity:
    payload = {
        "id": record["id"],
        "name": record["name"],
        "type": _map_activity_type(record["type"]),
        "start_date": _as_utc_iso(record["start_date_local"]),
        "elapsed_time": record["moving_time"],
        "distance": record["distance"],
        "total_elevation_gain": record.get("total_elevation_gain") or 0.0,
        "average_speed": record.get("average_speed") or 0.0,
        "average_heartrate": record.get("average_heartrate"),
        "max_heartrate": record.get("max_heartrate"),
        "has_heartrate": record.get("average_heartrate") is not None,
    }
    return Activity(**payload)


def _streams_to_activity_stream(records: list[dict]) -> ActivityStream:
    by_type = {r["type"]: r["data"] for r in records}
    series = {}
    for key in ("heartrate", "time", "distance"):
        data = by_type[key]
        series[key] = ActivityStreamSeries(
            data=data, series_type="time", original_size=len(data)
        )
    return ActivityStream(**series)


# Mock payload — mirrors MOCK_ACTIVITY_PAYLOAD's shape in strava_adapter.py,
# raw intervals.icu field names so MockIntervalsIcuAdapter exercises the
# same _record_to_activity()/_streams_to_activity_stream() mapping the real
# adapter uses.
MOCK_ACTIVITY_RECORD = {
    "id": 987654321,
    "name": "Tuesday Threshold - Track Session",
    "type": "Run",
    "start_date_local": "2026-06-23T06:30:00",
    "moving_time": 3247,
    "distance": 9843.2,
    "total_elevation_gain": 84.0,
    "average_speed": 3.173,
    "average_heartrate": 161.4,
    "max_heartrate": 178.0,
}


def _generate_mock_hr_stream(duration_s: int) -> list[float]:
    """Deterministic synthetic HR profile — same shape as
    strava_adapter._generate_mock_hr_stream, kept independent per-file so
    each provider's mock fixtures are self-contained."""
    hr = []
    for t in range(duration_s):
        if t < 600:
            hr.append(round(110 + (165 - 110) * (t / 600)))
        else:
            hr.append(165 + (3 if t % 20 < 10 else -3))
    return hr


_STREAM_DURATION = MOCK_ACTIVITY_RECORD["moving_time"]
_STREAM_DISTANCE_PER_SEC = MOCK_ACTIVITY_RECORD["distance"] / _STREAM_DURATION

MOCK_STREAM_RECORDS = [
    {"type": "heartrate", "data": _generate_mock_hr_stream(_STREAM_DURATION)},
    {"type": "time", "data": list(range(_STREAM_DURATION))},
    {"type": "distance", "data": [i * _STREAM_DISTANCE_PER_SEC for i in range(_STREAM_DURATION)]},
]


class MockIntervalsIcuAdapter:
    """Deterministic intervals.icu activity list, mirrors MockStravaAdapter."""

    def __init__(self, malformed: bool = False):
        self._malformed = malformed

    def get_new_activities(self, since_ts: int) -> list[Activity]:
        record = MOCK_ACTIVITY_RECORD
        if self._malformed:
            record = {"id": "not-an-int", "name": "bad activity"}

        try:
            activity = _record_to_activity(record)
        except (ValidationError, KeyError) as e:
            raise AdapterMalformedResponseError(str(e)) from e

        if activity.start_date.timestamp() <= since_ts:
            return []
        return [activity]

    def get_activity_stream(self, activity_id: int) -> ActivityStream | None:
        if activity_id != MOCK_ACTIVITY_RECORD["id"]:
            return None

        try:
            return _streams_to_activity_stream(MOCK_STREAM_RECORDS)
        except ValidationError as e:
            raise AdapterMalformedResponseError(str(e)) from e


class RealIntervalsIcuAdapter:
    """Drop-in replacement for MockIntervalsIcuAdapter behind
    ActivitySyncAdapterProtocol. No token refresh — the API key is a
    long-lived credential (docs/adr/0025 §1)."""

    def __init__(
        self,
        api_key: str,
        sleep_fn=time.sleep,
        now_fn=lambda: datetime.now(timezone.utc),
        http_client: httpx.Client | None = None,
    ):
        self._sleep = sleep_fn
        self._now = now_fn
        self._client = http_client or httpx.Client(
            base_url=INTERVALS_ICU_BASE_URL, auth=("API_KEY", api_key)
        )

    def _get(self, path: str, params: dict | None = None):
        for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
            try:
                response = self._client.get(path, params=params)
            except httpx.TimeoutException as e:
                raise AdapterTimeoutError(f"intervals.icu request timed out: {path}") from e
            except httpx.ConnectError as e:
                raise AdapterUnavailableError(f"intervals.icu connection failed: {path}") from e

            if response.status_code == 401:
                raise IntervalsIcuAuthError("401 from intervals.icu — invalid API key")
            if response.status_code == 404:
                raise IntervalsIcuActivityNotFoundError(f"404 from intervals.icu: {path}")
            if response.status_code == 429:
                if attempt < RATE_LIMIT_MAX_RETRIES:
                    retry_after = response.headers.get("Retry-After")
                    delay = int(retry_after) if retry_after else RATE_LIMIT_RETRY_DELAY_S
                    self._sleep(delay)
                    continue
                raise IntervalsIcuRateLimitError("intervals.icu rate limit — retries exhausted")

            response.raise_for_status()
            return response.json()

        raise IntervalsIcuRateLimitError("intervals.icu rate limit — retries exhausted")

    def get_new_activities(self, since_ts: int) -> list[Activity]:
        oldest = datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime("%Y-%m-%d")
        newest = self._now().strftime("%Y-%m-%d")

        records = self._get(
            "/athlete/0/activities",
            params={"oldest": oldest, "newest": newest, "fields": ACTIVITY_FIELDS},
        )
        try:
            activities = [_record_to_activity(r) for r in records]
        except (ValidationError, KeyError) as e:
            raise AdapterMalformedResponseError(str(e)) from e

        # oldest= is date-granular, not timestamp-granular — re-apply the
        # exact since_ts cutoff (mirrors strava_adapter's after= handling).
        return [a for a in activities if a.start_date.timestamp() > since_ts]

    def get_activity_stream(self, activity_id: int) -> ActivityStream | None:
        try:
            records = self._get(
                f"/activity/{activity_id}/streams.json",
                params={"types": "time,watts,distance,heartrate,cadence,altitude"},
            )
        except IntervalsIcuActivityNotFoundError:
            return None

        try:
            return _streams_to_activity_stream(records)
        except (ValidationError, KeyError) as e:
            raise AdapterMalformedResponseError(str(e)) from e
