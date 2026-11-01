"""F21.4: from a WHOOP event to daily_metrics, through the real adapter."""

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest

from apex_coach.adapters.errors import AdapterError
from apex_coach.adapters.whoop_adapter import WHOOP_BASE_URL, RealWhoopAdapter
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.token_repository import TokenRepository
from apex_coach.db.webhook_repository import IGNORED, PENDING, PROCESSED
from apex_coach.services.whoop_sync import process_event

STOCKHOLM = ZoneInfo("Europe/Stockholm")
SLEEP_ID = "3d0590ff-3739-4d9f-b14f-e7525a169699"
NOW = datetime(2026, 6, 23, 8, 0, tzinfo=timezone.utc)
DAY = "2026-06-23"


def _sleep(**overrides):
    return {
        "id": SLEEP_ID,
        "cycle_id": 93845,
        "start": "2026-06-22T21:00:00.000Z",
        "end": "2026-06-23T05:00:00.000Z",
        "nap": False,
        "score_state": "SCORED",
        "score": {
            "sleep_performance_percentage": 81.0,
            "stage_summary": {
                "total_in_bed_time_milli": 28800000,
                "total_awake_time_milli": 1800000,
            },
        },
        **overrides,
    }


def _recovery(**overrides):
    return {
        "cycle_id": 93845,
        "sleep_id": SLEEP_ID,
        "score_state": "SCORED",
        "score": {"recovery_score": 62.0, "resting_heart_rate": 48.6, "hrv_rmssd_milli": 71.4},
        **overrides,
    }


def _cycle(**overrides):
    return {
        "id": 93845,
        "start": "2026-06-22T21:00:00.000Z",
        "end": None,
        "score_state": "SCORED",
        "score": {"strain": 8.4},
        **overrides,
    }


class Whoop:
    def __init__(self, httpx_mock):
        self._mock = httpx_mock

    def sleep(self, payload=None, sleep_id=SLEEP_ID, status=200):
        self._mock.add_response(
            url=f"{WHOOP_BASE_URL}/developer/v2/activity/sleep/{sleep_id}",
            json=payload if payload is not None else _sleep(),
            status_code=status,
            is_optional=True,
            is_reusable=True,
        )

    def recovery(self, payload=None, status=200):
        self._mock.add_response(
            url=f"{WHOOP_BASE_URL}/developer/v2/cycle/93845/recovery",
            json=payload if payload is not None else _recovery(),
            status_code=status,
            is_optional=True,
            is_reusable=True,
        )

    def cycles(self, *records):
        self._mock.add_response(
            url=re.compile(re.escape(f"{WHOOP_BASE_URL}/developer/v2/cycle?") + ".*"),
            json={"records": list(records) or [_cycle()], "next_token": None},
            is_optional=True,
            is_reusable=True,
        )


@pytest.fixture
def whoop_api(httpx_mock):
    return Whoop(httpx_mock)


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def adapter(repository_engine, sleeps):
    tokens = TokenRepository(repository_engine, "test-key")
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    tokens.save_token("WHOOP", "access", "refresh", expires, "scope")
    return RealWhoopAdapter(
        tokens, "id", "secret", sleep_fn=sleeps.append, http_client=httpx.Client(base_url=WHOOP_BASE_URL)
    )


@pytest.fixture
def metrics(repository_engine):
    return MetricsRepository(repository_engine)


def _process(event_type, adapter, metrics, record_id=SLEEP_ID):
    return process_event(event_type, record_id, adapter, metrics, STOCKHOLM, now_fn=lambda: NOW)


def test_scored_event_writes_sleep_recovery_and_strain(whoop_api, adapter, metrics):
    whoop_api.sleep()
    whoop_api.recovery()
    whoop_api.cycles()

    assert _process("sleep.updated", adapter, metrics) == PROCESSED

    row = metrics.get_daily_metrics(DAY)
    assert row["whoop_sleep_hours"] == 7.5
    assert row["whoop_sleep_performance_pct"] == 81.0
    assert row["whoop_recovery_pct"] == 62.0
    assert row["whoop_hrv_ms"] == 71.4
    assert row["whoop_rhr_bpm"] == 49
    assert row["whoop_strain"] == 8.4
    assert row["whoop_sleep_id"] == SLEEP_ID
    assert row["whoop_cycle_id"] == "93845"
    assert row["whoop_recovery_score_state"] == "SCORED"
    assert row["whoop_synced_at"] == NOW.isoformat()


def test_recovery_event_id_is_the_sleep_uuid(whoop_api, adapter, metrics):
    whoop_api.sleep()
    whoop_api.recovery()
    whoop_api.cycles()

    assert _process("recovery.updated", adapter, metrics) == PROCESSED
    assert metrics.get_daily_metrics(DAY)["whoop_recovery_pct"] == 62.0


def test_two_events_for_one_day_give_one_row(whoop_api, adapter, metrics):
    whoop_api.sleep()
    whoop_api.recovery()
    whoop_api.cycles()

    _process("sleep.updated", adapter, metrics)
    _process("recovery.updated", adapter, metrics)

    assert [r["date"] for r in metrics.get_daily_metrics_range(DAY, DAY)] == [DAY]


def test_pending_sleep_writes_nothing_and_never_sleeps(whoop_api, adapter, metrics, sleeps):
    whoop_api.sleep(_sleep(score_state="PENDING_SCORE", score=None))

    assert _process("sleep.updated", adapter, metrics) == PENDING
    assert metrics.get_daily_metrics(DAY) is None
    assert sleeps == []


def test_pending_recovery_writes_no_recovery_metric_and_a_later_event_fills_it(
    whoop_api, adapter, metrics, httpx_mock, sleeps
):
    whoop_api.sleep()
    httpx_mock.add_response(
        url=f"{WHOOP_BASE_URL}/developer/v2/cycle/93845/recovery",
        json=_recovery(score_state="PENDING_SCORE", score=None),
    )
    httpx_mock.add_response(
        url=f"{WHOOP_BASE_URL}/developer/v2/cycle/93845/recovery", json=_recovery()
    )
    whoop_api.cycles()

    assert _process("sleep.updated", adapter, metrics) == PENDING
    row = metrics.get_daily_metrics(DAY)
    assert row["whoop_recovery_pct"] is None and row["whoop_recovery_score_state"] is None
    assert sleeps == []

    assert _process("recovery.updated", adapter, metrics) == PROCESSED
    assert metrics.get_daily_metrics(DAY)["whoop_recovery_pct"] == 62.0


def test_missing_recovery_counts_as_pending(whoop_api, adapter, metrics):
    whoop_api.sleep()
    whoop_api.recovery({"message": "not found"}, status=404)
    whoop_api.cycles()

    assert _process("sleep.updated", adapter, metrics) == PENDING


def test_unscorable_stores_state_with_null_metrics(whoop_api, adapter, metrics):
    whoop_api.sleep(_sleep(score_state="UNSCORABLE", score=None))
    whoop_api.recovery(_recovery(score_state="UNSCORABLE", score=None))
    whoop_api.cycles(_cycle(score_state="UNSCORABLE", score=None))

    assert _process("sleep.updated", adapter, metrics) == PROCESSED

    row = metrics.get_daily_metrics(DAY)
    assert row["whoop_recovery_score_state"] == "UNSCORABLE"
    assert row["whoop_recovery_pct"] is None
    assert row["whoop_sleep_hours"] is None
    assert row["whoop_strain"] is None


def test_nap_is_ignored(whoop_api, adapter, metrics):
    whoop_api.sleep(_sleep(nap=True))

    assert _process("sleep.updated", adapter, metrics) == IGNORED
    assert metrics.get_daily_metrics(DAY) is None


def test_shorter_second_sleep_on_the_same_date_loses(whoop_api, adapter, metrics):
    whoop_api.sleep()
    whoop_api.recovery()
    whoop_api.cycles()
    _process("sleep.updated", adapter, metrics)
    short_id = "11111111-3739-4d9f-b14f-e7525a169699"
    whoop_api.sleep(
        _sleep(id=short_id, start="2026-06-23T04:00:00.000Z", end="2026-06-23T05:30:00.000Z"),
        sleep_id=short_id,
    )

    assert _process("sleep.updated", adapter, metrics, record_id=short_id) == IGNORED
    assert metrics.get_daily_metrics(DAY)["whoop_sleep_id"] == SLEEP_ID


def test_longer_second_sleep_on_the_same_date_wins(whoop_api, adapter, metrics):
    whoop_api.sleep()
    whoop_api.recovery()
    whoop_api.cycles()
    _process("sleep.updated", adapter, metrics)
    long_id = "22222222-3739-4d9f-b14f-e7525a169699"
    whoop_api.sleep(
        _sleep(id=long_id, start="2026-06-22T19:00:00.000Z", end="2026-06-23T05:30:00.000Z"),
        sleep_id=long_id,
    )

    assert _process("sleep.updated", adapter, metrics, record_id=long_id) == PROCESSED
    assert metrics.get_daily_metrics(DAY)["whoop_sleep_id"] == long_id


@pytest.mark.parametrize("event_type", ["sleep.deleted", "recovery.deleted"])
def test_delete_clears_whoop_columns_and_keeps_the_row(whoop_api, adapter, metrics, event_type):
    whoop_api.sleep()
    whoop_api.recovery()
    whoop_api.cycles()
    _process("sleep.updated", adapter, metrics)
    metrics.upsert_daily_metrics(DAY, subjective_energy=4)

    assert _process(event_type, adapter, metrics) == PROCESSED

    row = metrics.get_daily_metrics(DAY)
    assert row["whoop_recovery_pct"] is None and row["whoop_sleep_hours"] is None
    assert row["whoop_sleep_id"] is None
    assert row["subjective_energy"] == 4


def test_delete_of_an_unknown_sleep_is_harmless(adapter, metrics):
    assert _process("sleep.deleted", adapter, metrics) == PROCESSED


@pytest.mark.parametrize("event_type", ["workout.updated", "workout.deleted", "something.new"])
def test_other_events_are_ignored_without_calling_whoop(adapter, metrics, httpx_mock, event_type):
    assert _process(event_type, adapter, metrics) == IGNORED
    assert httpx_mock.get_requests() == []


def test_rate_limit_waits_once_briefly_then_gives_up(whoop_api, adapter, metrics, httpx_mock, sleeps):
    httpx_mock.add_response(
        url=f"{WHOOP_BASE_URL}/developer/v2/activity/sleep/{SLEEP_ID}",
        status_code=429,
        is_reusable=True,
    )

    with pytest.raises(AdapterError):
        _process("sleep.updated", adapter, metrics)

    assert sum(sleeps) <= 2 and len(sleeps) == 1
    assert len(httpx_mock.get_requests()) == 2


def test_cycles_follow_pagination(adapter, httpx_mock):
    first = re.compile(re.escape(f"{WHOOP_BASE_URL}/developer/v2/cycle?") + ".*")
    httpx_mock.add_response(url=first, json={"records": [_cycle(id=1)], "next_token": "abc"})
    httpx_mock.add_response(url=first, json={"records": [_cycle(id=2)], "next_token": None})

    assert [c["id"] for c in adapter.get_cycles("2026-06-21T00:00:00+00:00")] == [1, 2]
    assert "nextToken=abc" in str(httpx_mock.get_requests()[1].url)
