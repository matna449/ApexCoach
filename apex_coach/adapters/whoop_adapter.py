"""WHOOP adapter Protocol + MockWhoopAdapter (ADR-0011).

get_daily_payload() is the only public method — it combines all 3 WHOOP
endpoints into one WhoopDailyPayload. Per-endpoint calls are internal.
"""

from typing import Protocol

from pydantic import ValidationError

from apex_coach.adapters.errors import AdapterMalformedResponseError
from apex_coach.models.pydantic_models import (
    WhoopCycle,
    WhoopDailyPayload,
    WhoopRecovery,
    WhoopSleep,
)

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
