from zoneinfo import ZoneInfo

import pytest

from apex_coach.services.whoop_day_mapping import (
    cycle_date,
    is_cycle_in_progress,
    local_date,
    sleep_date,
)

STOCKHOLM = ZoneInfo("Europe/Stockholm")


@pytest.mark.parametrize(
    ("end", "expected"),
    [
        ("2026-06-23T04:40:00.000Z", "2026-06-23"),  # 06:40 local
        ("2026-06-23T05:00:00.000Z", "2026-06-23"),  # slept across midnight, ends 07:00
        ("2026-06-22T22:30:00.000Z", "2026-06-23"),  # 00:30 local, already the next date
        ("2026-01-15T23:30:00.000Z", "2026-01-16"),  # winter offset is +1, not +2
        ("2026-03-29T00:30:00.000Z", "2026-03-29"),  # spring DST day, 01:30 local
        ("2026-03-29T01:30:00.000Z", "2026-03-29"),  # 03:30 local, 02:30 never existed
        ("2026-10-24T22:30:00.000Z", "2026-10-25"),  # autumn DST day, 00:30 local
        ("2026-10-25T00:30:00.000Z", "2026-10-25"),  # first 02:30 local
        ("2026-10-25T01:30:00.000Z", "2026-10-25"),  # second 02:30 local
    ],
)
def test_sleep_belongs_to_the_local_date_it_ends_on(end, expected):
    assert sleep_date({"end": end}, STOCKHOLM) == expected


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        ("2026-06-22T20:30:00.000Z", "2026-06-23"),  # 22:30 local goes to the next date
        ("2026-06-22T23:00:00.000Z", "2026-06-23"),  # 01:00 local stays
        ("2026-06-23T07:00:00.000Z", "2026-06-23"),  # 09:00 local stays
        ("2026-10-24T20:30:00.000Z", "2026-10-25"),  # 22:30 before the autumn DST change
        ("2026-03-28T21:30:00.000Z", "2026-03-29"),  # 22:30 before the spring DST change
    ],
)
def test_cycle_belongs_to_its_start_plus_six_hours(start, expected):
    assert cycle_date({"start": start}, STOCKHOLM) == expected


def test_cycle_without_an_end_is_in_progress():
    assert is_cycle_in_progress({"start": "2026-06-23T04:00:00Z", "end": None})
    assert is_cycle_in_progress({"start": "2026-06-23T04:00:00Z"})
    assert not is_cycle_in_progress({"end": "2026-06-23T04:00:00Z"})


def test_offsets_in_the_timestamp_are_respected():
    assert local_date("2026-06-23T01:00:00+02:00", STOCKHOLM) == "2026-06-23"
