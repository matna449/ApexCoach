import pytest

from apex_coach.adapters.errors import AdapterMalformedResponseError
from apex_coach.adapters.strava_adapter import MOCK_ACTIVITY_PAYLOAD, MockStravaAdapter
from apex_coach.models.pydantic_models import StravaActivity, StravaStream


def test_get_new_activities_returns_typed_activities_matching_mock_data():
    adapter = MockStravaAdapter()

    activities = adapter.get_new_activities(since_ts=0)

    assert len(activities) == 1
    activity = activities[0]
    assert isinstance(activity, StravaActivity)
    assert activity.name == "Tuesday Threshold - Track Session"
    assert activity.type == "Run"
    assert activity.distance == 9843.2
    assert activity.elapsed_time == 3247
    assert activity.average_heartrate == 161.4
    assert activity.total_elevation_gain == 84.0


def test_pace_sec_per_km_computed_from_average_speed():
    adapter = MockStravaAdapter()

    activity = adapter.get_new_activities(since_ts=0)[0]

    assert activity.pace_sec_per_km == pytest.approx(1000 / 3.173, abs=0.01)


def test_grade_pct_computed_from_elevation_and_distance():
    adapter = MockStravaAdapter()

    activity = adapter.get_new_activities(since_ts=0)[0]

    assert activity.grade_pct == pytest.approx((84.0 / 9843.2) * 100, abs=0.001)


def test_splits_metric_parsed_as_typed_splits():
    adapter = MockStravaAdapter()

    activity = adapter.get_new_activities(since_ts=0)[0]

    assert len(activity.splits_metric) == 1
    assert activity.splits_metric[0].split == 1
    assert activity.splits_metric[0].average_heartrate == 154.2


def test_malformed_payload_raises_adapter_malformed_response_error():
    adapter = MockStravaAdapter(malformed=True)

    with pytest.raises(AdapterMalformedResponseError):
        adapter.get_new_activities(since_ts=0)


def test_since_ts_after_activity_returns_no_activities():
    adapter = MockStravaAdapter()

    # Mock activity starts 2026-06-23T06:30:00Z; anything after that should
    # be treated as already synced, matching the real `after` query param.
    activities = adapter.get_new_activities(since_ts=9999999999)

    assert activities == []


def test_since_ts_before_activity_returns_the_activity():
    adapter = MockStravaAdapter()

    activities = adapter.get_new_activities(since_ts=0)

    assert len(activities) == 1


# -- get_activity_stream — API Contract §3.3 --------------------------------


def test_get_activity_stream_returns_typed_stream_for_known_activity():
    adapter = MockStravaAdapter()

    stream = adapter.get_activity_stream(MOCK_ACTIVITY_PAYLOAD["id"])

    assert isinstance(stream, StravaStream)
    assert len(stream.heartrate.data) == MOCK_ACTIVITY_PAYLOAD["elapsed_time"]
    assert len(stream.heartrate.data) == len(stream.time.data) == len(stream.distance.data)


def test_get_activity_stream_returns_none_for_unknown_activity():
    adapter = MockStravaAdapter()

    assert adapter.get_activity_stream(999999) is None
