import pytest

from apex_coach.adapters.errors import AdapterMalformedResponseError
from apex_coach.adapters.whoop_adapter import MockWhoopAdapter
from apex_coach.models.pydantic_models import WhoopDailyPayload


def test_get_daily_payload_returns_typed_payload_matching_mock_data():
    adapter = MockWhoopAdapter()

    payload = adapter.get_daily_payload("2026-07-30")

    assert isinstance(payload, WhoopDailyPayload)
    assert payload.date == "2026-07-30"
    assert payload.whoop_recovery_pct == 62.0
    assert payload.whoop_hrv_ms == 71.4
    assert payload.whoop_rhr_bpm == 48.0
    assert payload.whoop_strain == 8.4


def test_get_daily_payload_computes_sleep_hours_from_stage_summary():
    adapter = MockWhoopAdapter()

    payload = adapter.get_daily_payload("2026-07-30")

    # (28200000 - 1620000) ms asleep / 1000 / 60 / 60
    assert payload.whoop_sleep_hours == pytest.approx(7.383, abs=0.001)


def test_malformed_payload_raises_adapter_malformed_response_error():
    adapter = MockWhoopAdapter(malformed=True)

    with pytest.raises(AdapterMalformedResponseError):
        adapter.get_daily_payload("2026-07-30")


def test_mock_sleep_payload_matches_api_contract_2_4_nesting():
    from apex_coach.adapters.whoop_adapter import MOCK_SLEEP_PAYLOAD
    from apex_coach.models.pydantic_models import WhoopSleep

    # API Contract §2.4's mock payload nests these fields under
    # score.stage_summary, not directly on score — a flat shape would
    # fail this validation.
    sleep = WhoopSleep(**MOCK_SLEEP_PAYLOAD)
    assert sleep.score.stage_summary.total_in_bed_time_milli == 28200000
