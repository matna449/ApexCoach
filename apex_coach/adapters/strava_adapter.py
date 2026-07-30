"""Strava adapter Protocol + MockStravaAdapter (API Contract §3.2, §3.3).

get_activity_stream() (§3.3) added in F06.1 — see docs/adr/0014 for why
this ticket builds it rather than deferring it further.
"""

from typing import Protocol

from pydantic import ValidationError

from apex_coach.adapters.errors import AdapterMalformedResponseError
from apex_coach.models.pydantic_models import StravaActivity, StravaStream

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
