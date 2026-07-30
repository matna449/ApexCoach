"""Strava adapter Protocol + MockStravaAdapter (API Contract §3.2).

Only get_new_activities() is in scope here — get_activity_stream() (§3.3)
is a separate endpoint used later for time-in-zone analysis, not needed
for the activity list this ticket builds.
"""

from typing import Protocol

from pydantic import ValidationError

from apex_coach.adapters.errors import AdapterMalformedResponseError
from apex_coach.models.pydantic_models import StravaActivity

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


class StravaAdapterProtocol(Protocol):
    def get_new_activities(self, since_ts: int) -> list[StravaActivity]: ...


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
