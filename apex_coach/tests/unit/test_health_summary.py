import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from apex_coach.services.health_summary import build_daily_health, rows_needed_from

STOCKHOLM = ZoneInfo("Europe/Stockholm")
TODAY = date(2026, 10, 31)
MORNING = datetime(2026, 10, 31, 7, 0, tzinfo=STOCKHOLM)
LATE = datetime(2026, 10, 31, 11, 0, tzinfo=STOCKHOLM)

_COLUMNS = (
    "whoop_recovery_pct",
    "whoop_hrv_ms",
    "whoop_rhr_bpm",
    "whoop_strain",
    "whoop_sleep_hours",
    "whoop_sleep_performance_pct",
    "whoop_synced_at",
    "rpe_yesterday",
    "soreness_note",
    "muscle_soreness",
    "sleep_quality_felt",
    "subjective_energy",
    "subjective_stress",
    "pain_note",
)


def _row(days_ago=0, **values):
    day = TODAY - timedelta(days=days_ago)
    return {"date": day.isoformat(), **dict.fromkeys(_COLUMNS), **values}


def _build(rows, days=14, now=MORNING, reauth=False, pending=0):
    return build_daily_health(rows, days, reauth, pending, now)


def _today(rows, **kwargs):
    return _build(rows, **kwargs)["days"][0]


def _hrv_history(values, start_days_ago=1):
    return [_row(start_days_ago + i, whoop_hrv_ms=v) for i, v in enumerate(values)]


def test_values_are_mapped_and_rounded():
    day = _today(
        [
            _row(
                whoop_recovery_pct=33.4,
                whoop_hrv_ms=51.52,
                whoop_rhr_bpm=54,
                whoop_strain=4.23,
                whoop_sleep_hours=6.54,
                whoop_sleep_performance_pct=71.2,
                rpe_yesterday=3,
                soreness_note="calf",
                muscle_soreness=2,
                sleep_quality_felt=2,
                subjective_energy=5,
                subjective_stress=1,
                pain_note="knee",
            )
        ]
    )

    assert day["date"] == "2026-10-31"
    assert (day["recovery_pct"], day["hrv_ms"], day["resting_hr_bpm"]) == (33, 51.5, 54)
    assert (day["strain"], day["sleep_hours"], day["sleep_performance_pct"]) == (4.2, 6.5, 71)
    assert day["subjective"] == {
        "rpe_yesterday": 3,
        "soreness": "calf",
        "soreness_level": 2,
        "sleep_quality": 2,
        "energy": 5,
        "stress": 1,
        "pain": "knee",
    }


def test_averages_exclude_the_day_itself():
    rows = [_row(whoop_hrv_ms=1000.0, whoop_rhr_bpm=99), *_hrv_history([60.0, 70.0, 80.0])]
    rows[1]["whoop_rhr_bpm"] = rows[2]["whoop_rhr_bpm"] = rows[3]["whoop_rhr_bpm"] = 50

    day = _today(rows)

    assert day["hrv_7d_avg"] == 70.0
    assert day["rhr_7d_avg"] == 50.0


def test_7d_average_only_looks_seven_days_back():
    assert _today(_hrv_history([60.0, 60.0, 60.0, 60.0, 60.0, 60.0, 60.0, 500.0]))["hrv_7d_avg"] == 60.0


@pytest.mark.parametrize(("samples", "expected"), [(2, None), (3, 60.0)])
def test_7d_average_needs_three_samples(samples, expected):
    assert _today(_hrv_history([60.0] * samples))["hrv_7d_avg"] == expected


@pytest.mark.parametrize(("samples", "expected"), [(6, None), (7, 60.0)])
def test_30d_average_follows_adr_0021_minimum(samples, expected):
    assert _today(_hrv_history([60.0] * samples))["hrv_30d_avg"] == expected


def test_30d_average_stops_at_day_minus_30():
    rows = _hrv_history([60.0] * 30) + [_row(31, whoop_hrv_ms=900.0), _row(whoop_hrv_ms=900.0)]

    assert _today(rows)["hrv_30d_avg"] == 60.0


@pytest.mark.parametrize(
    ("recovery", "flagged"), [(33.9, True), (34.0, False), (34, False), (None, False)]
)
def test_recovery_red_is_strictly_below_34(recovery, flagged):
    assert ("RECOVERY_RED" in _today([_row(whoop_recovery_pct=recovery)])["flags"]) is flagged


@pytest.mark.parametrize(
    ("hrv", "flagged"), [(80.0, False), (79.9, True), (80.1, False), (None, False)]
)
def test_hrv_flag_is_strictly_below_minus_20_percent(hrv, flagged):
    rows = [_row(whoop_hrv_ms=hrv), *_hrv_history([100.0, 100.0, 100.0])]

    assert ("HRV_BELOW_7D_20PCT" in _today(rows)["flags"]) is flagged


def test_no_hrv_flag_without_a_7d_average():
    assert "HRV_BELOW_7D_20PCT" not in _today([_row(whoop_hrv_ms=1.0)])["flags"]


def _recoveries(*values):
    return [_row(i, whoop_recovery_pct=v) for i, v in enumerate(values)]


@pytest.mark.parametrize(
    ("values", "flagged"),
    [
        ((20, 20, 20), True),
        ((20, 20, 34), False),
        ((34, 20, 20), False),
        ((20, 20), False),
        ((20, None, 20), False),
    ],
)
def test_low_recovery_streak_needs_three_consecutive_red_days(values, flagged):
    assert ("LOW_RECOVERY_3D" in _today(_recoveries(*values))["flags"]) is flagged


def test_a_gap_in_days_breaks_the_streak():
    rows = [_row(0, whoop_recovery_pct=20), _row(1, whoop_recovery_pct=20), _row(3, whoop_recovery_pct=20)]

    assert "LOW_RECOVERY_3D" not in _today(rows)["flags"]


def test_today_has_an_entry_even_without_a_row_and_other_gaps_are_left_out():
    days = _build([_row(2, whoop_hrv_ms=60.0)])["days"]

    assert [d["date"] for d in days] == ["2026-10-31", "2026-10-29"]
    assert days[0]["recovery_pct"] is None


def test_days_limits_the_response_but_not_the_averages():
    days = _build(_hrv_history([60.0] * 9), days=1)["days"]

    assert len(days) == 1
    assert days[0]["hrv_7d_avg"] == 60.0


@pytest.mark.parametrize(
    ("now", "rows", "stale"),
    [
        (LATE, [], True),
        (LATE, [_row(subjective_energy=4)], True),
        (LATE, [_row(whoop_hrv_ms=60.0)], False),
        (MORNING, [], False),
    ],
    ids=["no-row", "only-answers", "has-data", "before-ten"],
)
def test_sync_stale_flag(now, rows, stale):
    assert ("SYNC_STALE" in _today(rows, now=now)["flags"]) is stale


def test_sync_stale_only_applies_to_today():
    days = _build([_row(whoop_hrv_ms=60.0), _row(1, subjective_energy=4)], now=LATE)["days"]

    assert days[1]["flags"] == []


def test_strain_in_progress_is_on_today_only():
    days = _build([_row(whoop_strain=4.2), _row(1, whoop_strain=8.0)])["days"]

    assert days[0]["strain_in_progress"] is True
    assert "strain_in_progress" not in days[1]


def _synced(hours_ago):
    return (MORNING - timedelta(hours=hours_ago)).isoformat()


@pytest.mark.parametrize(
    ("rows", "reauth", "now", "expected"),
    [
        ([_row(whoop_hrv_ms=60.0, whoop_synced_at=_synced(1))], False, MORNING, "OK"),
        ([_row(whoop_hrv_ms=60.0, whoop_synced_at=_synced(1))], True, MORNING, "REAUTH_REQUIRED"),
        ([_row(1, whoop_synced_at=_synced(35))], False, MORNING, "OK"),
        ([_row(1, whoop_synced_at=_synced(37))], False, MORNING, "STALE"),
        ([_row(1, whoop_synced_at=_synced(1))], False, LATE, "STALE"),
        ([], False, MORNING, "STALE"),
        ([], True, LATE, "REAUTH_REQUIRED"),
    ],
    ids=["ok", "reauth", "35h", "37h", "no-data-after-ten", "never", "reauth-wins"],
)
def test_sync_status(rows, reauth, now, expected):
    assert _build(rows, reauth=reauth, now=now)["sync"]["status"] == expected


def test_sync_reports_the_latest_sync_and_pending_events():
    rows = [_row(whoop_synced_at=_synced(5)), _row(1, whoop_synced_at=_synced(1))]

    sync = _build(rows, pending=2)["sync"]

    assert sync["last_synced_at"] == _synced(1)
    assert sync["pending_events"] == 2


def test_14_day_response_is_under_4_kb():
    rows = [
        _row(
            i,
            # A three-day red streak, like the spec's example flags.
            whoop_recovery_pct=20.0 if i < 3 else 60.0,
            whoop_hrv_ms=65.62244,
            whoop_rhr_bpm=50,
            whoop_strain=13.701951,
            whoop_sleep_hours=7.123456,
            whoop_sleep_performance_pct=81.0,
            whoop_synced_at=_synced(1),
            rpe_yesterday=3,
            sleep_quality_felt=2,
            subjective_energy=5,
            subjective_stress=1,
        )
        for i in range(44)
    ]

    response = _build(rows)

    assert len(response["days"]) == 14
    assert len(json.dumps(response, separators=(",", ":")).encode()) < 4096


def test_unanswered_subjective_fields_are_left_out():
    assert _today([_row(subjective_energy=5)])["subjective"] == {"energy": 5}
    assert _today([_row()])["subjective"] == {}


def test_rows_needed_reach_the_oldest_days_30_day_window():
    assert rows_needed_from(TODAY, 14) == TODAY - timedelta(days=43)
