from datetime import datetime, timezone

import httpx
import pytest

from apex_coach.adapters.errors import AdapterMalformedResponseError, AdapterTimeoutError
from apex_coach.adapters.intervals_icu_adapter import (
    ACTIVITY_FIELDS,
    RATE_LIMIT_MAX_RETRIES,
    IntervalsIcuAuthError,
    IntervalsIcuRateLimitError,
    IntervalsIcuUnmappedActivityTypeError,
    RealIntervalsIcuAdapter,
)

FIXED_NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
ACTIVITIES_URL = (
    f"https://intervals.icu/api/v1/athlete/0/activities"
    f"?oldest=1970-01-01&newest=2026-07-30&fields={ACTIVITY_FIELDS}"
)


def _record(activity_id: int | str, activity_type: str = "Run", start: str = "2026-07-30T06:00:00") -> dict:
    return {
        "id": activity_id,
        "name": f"Run {activity_id}",
        "type": activity_type,
        "start_date_local": start,
        "moving_time": 1800,
        "distance": 5000.0,
        "total_elevation_gain": 20.0,
        "average_speed": 2.78,
        "average_heartrate": 150.0,
        "max_heartrate": 165.0,
    }


STREAM_RECORDS = [
    {"type": "heartrate", "data": [140.0, 145.0, 150.0]},
    {"type": "time", "data": [0.0, 1.0, 2.0]},
    {"type": "distance", "data": [0.0, 3.0, 6.0]},
]


@pytest.fixture
def sleeps():
    calls = []
    return calls, (lambda seconds: calls.append(seconds))


def _adapter(sleep_fn):
    return RealIntervalsIcuAdapter("test-api-key", sleep_fn=sleep_fn, now_fn=lambda: FIXED_NOW)


# -- get_new_activities --------------------------------------------------------


def test_get_new_activities_maps_records_to_typed_activities(httpx_mock, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(url=ACTIVITIES_URL, json=[_record(1), _record(2)])

    adapter = _adapter(sleep_fn)
    activities = adapter.get_new_activities(0)

    assert [a.id for a in activities] == [1, 2]
    assert activities[0].type == "Run"
    assert activities[0].has_heartrate is True


def test_get_new_activities_accepts_prefixed_string_ids(httpx_mock, sleeps):
    """Real intervals.icu ids are strings like "i171360215", not plain
    integers — caught during F18.5/#94's live run against a real account."""
    _, sleep_fn = sleeps
    httpx_mock.add_response(url=ACTIVITIES_URL, json=[_record("i171360215")])

    adapter = _adapter(sleep_fn)
    activities = adapter.get_new_activities(0)

    assert activities[0].id == "i171360215"


def test_get_new_activities_applies_activity_type_mapping(httpx_mock, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(
        url=ACTIVITIES_URL,
        json=[_record(1, activity_type="VirtualRide"), _record(2, activity_type="Crossfit")],
    )

    adapter = _adapter(sleep_fn)
    activities = adapter.get_new_activities(0)

    assert activities[0].type == "Ride"
    assert activities[1].type == "WeightTraining"


def test_get_new_activities_unmapped_type_raises(httpx_mock, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(url=ACTIVITIES_URL, json=[_record(1, activity_type="Kayaking")])

    adapter = _adapter(sleep_fn)
    with pytest.raises(IntervalsIcuUnmappedActivityTypeError):
        adapter.get_new_activities(0)


def test_get_new_activities_reapplies_since_ts_cutoff(httpx_mock, sleeps):
    _, sleep_fn = sleeps
    since_ts = int(datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc).timestamp())
    same_day_url = (
        f"https://intervals.icu/api/v1/athlete/0/activities"
        f"?oldest=2026-07-30&newest=2026-07-30&fields={ACTIVITY_FIELDS}"
    )
    httpx_mock.add_response(
        url=same_day_url, json=[_record(1, start="2026-07-30T06:00:00")]
    )

    adapter = _adapter(sleep_fn)
    assert adapter.get_new_activities(since_ts) == []


def test_malformed_response_raises_adapter_malformed_response_error(httpx_mock, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(url=ACTIVITIES_URL, json=[{"id": "not-an-int"}])

    adapter = _adapter(sleep_fn)
    with pytest.raises(AdapterMalformedResponseError):
        adapter.get_new_activities(0)


# -- Failure modes --------------------------------------------------------------


def test_401_raises_auth_error(httpx_mock, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(url=ACTIVITIES_URL, status_code=401)

    adapter = _adapter(sleep_fn)
    with pytest.raises(IntervalsIcuAuthError):
        adapter.get_new_activities(0)


def test_429_retries_using_retry_after_header_then_succeeds(httpx_mock, sleeps):
    calls, sleep_fn = sleeps
    httpx_mock.add_response(url=ACTIVITIES_URL, status_code=429, headers={"Retry-After": "5"})
    httpx_mock.add_response(url=ACTIVITIES_URL, json=[])

    adapter = _adapter(sleep_fn)
    assert adapter.get_new_activities(0) == []
    assert calls == [5]


def test_429_falls_back_to_default_delay_without_retry_after_header(httpx_mock, sleeps):
    calls, sleep_fn = sleeps
    httpx_mock.add_response(url=ACTIVITIES_URL, status_code=429)
    httpx_mock.add_response(url=ACTIVITIES_URL, json=[])

    adapter = _adapter(sleep_fn)
    assert adapter.get_new_activities(0) == []
    assert calls == [900]


def test_429_exhausts_retries_and_raises(httpx_mock, sleeps):
    _, sleep_fn = sleeps
    for _ in range(RATE_LIMIT_MAX_RETRIES + 1):
        httpx_mock.add_response(url=ACTIVITIES_URL, status_code=429)

    adapter = _adapter(sleep_fn)
    with pytest.raises(IntervalsIcuRateLimitError):
        adapter.get_new_activities(0)


def test_network_timeout_raises_adapter_timeout_error(httpx_mock, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_exception(httpx.TimeoutException("timed out"), url=ACTIVITIES_URL)

    adapter = _adapter(sleep_fn)
    with pytest.raises(AdapterTimeoutError):
        adapter.get_new_activities(0)


# -- get_activity_stream --------------------------------------------------------


def test_get_activity_stream_happy_path(httpx_mock, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(
        url="https://intervals.icu/api/v1/activity/42/streams.json"
        "?types=time%2Cwatts%2Cdistance%2Cheartrate%2Ccadence%2Caltitude",
        json=STREAM_RECORDS,
    )

    adapter = _adapter(sleep_fn)
    stream = adapter.get_activity_stream(42)

    assert stream is not None
    assert stream.heartrate.data == [140.0, 145.0, 150.0]


def test_get_activity_stream_404_returns_none(httpx_mock, sleeps):
    _, sleep_fn = sleeps
    httpx_mock.add_response(
        url="https://intervals.icu/api/v1/activity/42/streams.json"
        "?types=time%2Cwatts%2Cdistance%2Cheartrate%2Ccadence%2Caltitude",
        status_code=404,
    )

    adapter = _adapter(sleep_fn)
    assert adapter.get_activity_stream(42) is None
