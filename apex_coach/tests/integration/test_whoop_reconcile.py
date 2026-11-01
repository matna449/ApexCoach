"""F21.5: the daily reconcile restores whatever webhooks missed."""

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx
import pytest

from apex_coach.adapters.whoop_adapter import WHOOP_BASE_URL, RealWhoopAdapter
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.token_repository import TokenRepository
from apex_coach.services.whoop_sync import reconcile

STOCKHOLM = ZoneInfo("Europe/Stockholm")
NOW = datetime(2026, 6, 23, 3, 30, tzinfo=timezone.utc)
TODAY = "2026-06-23"
BASE = f"{WHOOP_BASE_URL}/developer/v2"


def _sleep(id_="s1", start="2026-06-22T21:00:00Z", end="2026-06-23T03:00:00Z", **overrides):
    return {
        "id": id_,
        "cycle_id": 1,
        "start": start,
        "end": end,
        "nap": False,
        "score_state": "SCORED",
        "score": {
            "sleep_performance_percentage": 81.0,
            "stage_summary": {
                "total_in_bed_time_milli": 21600000,
                "total_awake_time_milli": 3600000,
            },
        },
        **overrides,
    }


def _recovery(sleep_id="s1", **overrides):
    return {
        "cycle_id": 1,
        "sleep_id": sleep_id,
        "score_state": "SCORED",
        "score": {"recovery_score": 62.0, "resting_heart_rate": 48.0, "hrv_rmssd_milli": 71.4},
        **overrides,
    }


def _cycle(start="2026-06-22T21:00:00Z", strain=8.4, **overrides):
    return {
        "id": 1,
        "start": start,
        "end": None,
        "score_state": "SCORED",
        "score": {"strain": strain},
        **overrides,
    }


def _mock(httpx_mock, sleeps=(), recoveries=(), cycles=()):
    for path, records in (("activity/sleep", sleeps), ("recovery", recoveries), ("cycle", cycles)):
        httpx_mock.add_response(
            url=re.compile(re.escape(f"{BASE}/{path}?") + ".*"),
            json={"records": list(records), "next_token": None},
        )


@pytest.fixture
def adapter(repository_engine):
    tokens = TokenRepository(repository_engine, "test-key")
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    tokens.save_token("WHOOP", "access", "refresh", expires, "scope")
    return RealWhoopAdapter(tokens, "id", "secret", http_client=httpx.Client(base_url=WHOOP_BASE_URL))


@pytest.fixture
def metrics(repository_engine):
    return MetricsRepository(repository_engine)


def _reconcile(adapter, metrics, **kwargs):
    return reconcile(adapter, metrics, STOCKHOLM, now_fn=lambda: NOW, **kwargs)


def test_restores_todays_whoop_columns_and_keeps_subjective_answers(adapter, metrics, httpx_mock):
    metrics.upsert_daily_metrics(TODAY, subjective_energy=4)
    _mock(httpx_mock, [_sleep()], [_recovery()], [_cycle()])

    counts = _reconcile(adapter, metrics)

    assert counts == {"sleeps": 1, "recoveries": 1, "cycles": 1}
    row = metrics.get_daily_metrics(TODAY)
    assert row["whoop_recovery_pct"] == 62.0
    assert row["whoop_sleep_hours"] == 5.0
    assert row["whoop_strain"] == 8.4
    assert row["subjective_energy"] == 4
    assert row["whoop_synced_at"] == NOW.isoformat()


def test_default_window_is_three_local_days(adapter, metrics, httpx_mock):
    old_sleep = _sleep("old", "2026-06-19T21:00:00Z", "2026-06-20T03:00:00Z")
    edge_sleep = _sleep("edge", "2026-06-20T21:00:00Z", "2026-06-21T03:00:00Z")
    _mock(httpx_mock, [edge_sleep, old_sleep], [], [_cycle("2026-06-19T21:00:00Z")])

    _reconcile(adapter, metrics)

    assert metrics.get_daily_metrics("2026-06-21")["whoop_sleep_id"] == "edge"
    assert metrics.get_daily_metrics("2026-06-20") is None


def test_days_widens_the_fetched_window(adapter, metrics, httpx_mock):
    _mock(httpx_mock)

    _reconcile(adapter, metrics, days=30)

    start = parse_qs(urlparse(str(httpx_mock.get_requests()[0].url)).query)["start"][0]
    assert start.startswith("2026-05-23")


def test_naps_and_pending_records_write_nothing(adapter, metrics, httpx_mock):
    _mock(
        httpx_mock,
        [_sleep("nap", nap=True), _sleep("p", score_state="PENDING_SCORE", score=None)],
        [],
        [_cycle(score_state="PENDING_SCORE", score=None)],
    )

    assert _reconcile(adapter, metrics)["sleeps"] == 0
    assert metrics.get_daily_metrics(TODAY) is None


def test_longest_sleep_on_a_date_wins(adapter, metrics, httpx_mock):
    short = _sleep("short", "2026-06-23T01:00:00Z", "2026-06-23T02:00:00Z")
    long = _sleep("long", "2026-06-22T20:00:00Z", "2026-06-23T03:00:00Z")
    _mock(httpx_mock, [short, long], [_recovery("long")], [])

    _reconcile(adapter, metrics)

    assert metrics.get_daily_metrics(TODAY)["whoop_sleep_id"] == "long"


def test_pending_recovery_is_left_for_later(adapter, metrics, httpx_mock):
    _mock(httpx_mock, [_sleep()], [_recovery(score_state="PENDING_SCORE", score=None)], [])

    counts = _reconcile(adapter, metrics)

    assert counts["recoveries"] == 0
    assert metrics.get_daily_metrics(TODAY)["whoop_recovery_pct"] is None


def test_is_idempotent(adapter, metrics, httpx_mock):
    for _ in range(2):
        _mock(httpx_mock, [_sleep()], [_recovery()], [_cycle()])
        _reconcile(adapter, metrics)

    assert len(metrics.get_daily_metrics_range(TODAY, TODAY)) == 1
