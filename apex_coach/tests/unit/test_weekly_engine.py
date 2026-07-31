import pytest

from apex_coach.engines.weekly_engine import (
    apply_recovery_week_protocol,
    apply_skip,
    decide_skip_disposition,
    decide_state_transition,
    select_reschedule_slot,
    two_consecutive_red_days,
)


# -- decide_state_transition — §4.1 -----------------------------------------


def test_any_state_transitions_to_complete_at_end_of_week():
    for state in ("ON_TRACK", "LOAD_DEFICIT", "OVERREACHED", "RECOVERY_WEEK"):
        assert decide_state_transition(state, end_of_week_reached=True) == "COMPLETE"


def test_on_track_to_load_deficit_when_key_session_skipped_and_load_low():
    result = decide_state_transition("ON_TRACK", key_session_skipped=True, load_pct=79.0)
    assert result == "LOAD_DEFICIT"


def test_on_track_stays_on_track_if_load_deficit_condition_not_fully_met():
    # skipped but load isn't below 80%
    assert decide_state_transition("ON_TRACK", key_session_skipped=True, load_pct=85.0) == "ON_TRACK"
    # load low but nothing skipped
    assert decide_state_transition("ON_TRACK", key_session_skipped=False, load_pct=50.0) == "ON_TRACK"


def test_on_track_to_overreached():
    result = decide_state_transition("ON_TRACK", overreached_3_consecutive_days=True)
    assert result == "OVERREACHED"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"monthly_engine_triggers_recovery": True},
        {"two_consecutive_red_days": True},
    ],
)
def test_on_track_to_recovery_week(kwargs):
    assert decide_state_transition("ON_TRACK", **kwargs) == "RECOVERY_WEEK"


def test_load_deficit_to_on_track_when_rescheduled_session_completed():
    result = decide_state_transition("LOAD_DEFICIT", rescheduled_session_completed=True)
    assert result == "ON_TRACK"


def test_load_deficit_to_recovery_week_when_not_recoverable():
    result = decide_state_transition("LOAD_DEFICIT", monthly_load_not_recoverable=True)
    assert result == "RECOVERY_WEEK"


def test_load_deficit_stays_load_deficit_otherwise():
    assert decide_state_transition("LOAD_DEFICIT") == "LOAD_DEFICIT"


def test_overreached_automatically_becomes_recovery_week():
    assert decide_state_transition("OVERREACHED") == "RECOVERY_WEEK"


def test_recovery_week_stays_recovery_week_without_end_of_week():
    assert decide_state_transition("RECOVERY_WEEK") == "RECOVERY_WEEK"


def test_complete_is_terminal():
    assert decide_state_transition("COMPLETE") == "COMPLETE"


def test_unknown_state_raises():
    with pytest.raises(ValueError):
        decide_state_transition("BOGUS")


# -- two_consecutive_red_days -------------------------------------------------


def test_two_consecutive_red_days_true_when_both_red():
    assert two_consecutive_red_days([20.0, 15.0]) is True


def test_two_consecutive_red_days_false_when_one_not_red():
    assert two_consecutive_red_days([20.0, 50.0]) is False


def test_two_consecutive_red_days_false_with_insufficient_history():
    assert two_consecutive_red_days([20.0]) is False
    assert two_consecutive_red_days([]) is False


# -- select_reschedule_slot — §4.2 -------------------------------------------


def test_select_reschedule_slot_finds_day_with_full_gap_from_key_session():
    planned = [
        {"day": "Monday", "session_type": "HIIT"},
        {"day": "Tuesday", "session_type": "Zone2_Short"},
        {"day": "Wednesday", "session_type": "Zone2_Long"},
    ]
    # Monday is KEY. Tuesday is adjacent (0 days between) -> rejected.
    # Wednesday has 1 full day (Tuesday) between it and Monday -> valid.
    assert select_reschedule_slot(planned) == "Wednesday"


def test_select_reschedule_slot_skips_key_and_rest_days():
    planned = [
        {"day": "Monday", "session_type": "Rest"},
        {"day": "Tuesday", "session_type": "Threshold"},
    ]
    # Monday is Rest (excluded). Tuesday is KEY (excluded). Wednesday is
    # adjacent to Tuesday's KEY session (0 full days between) -> also
    # rejected. Thursday has 1 full day (Wednesday) between it and
    # Tuesday's KEY session -> first valid slot.
    assert select_reschedule_slot(planned) == "Thursday"


def test_select_reschedule_slot_returns_none_when_fully_booked_with_key_sessions():
    planned = [{"day": d, "session_type": "HIIT"} for d in
               ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]]
    assert select_reschedule_slot(planned) is None


# -- decide_skip_disposition — §4.2 ------------------------------------------


def test_reschedule_when_all_conditions_met():
    result = decide_skip_disposition(
        days_remaining_in_week=3, monthly_load_pct=70.0, current_week_state="ON_TRACK", reschedule_slot="Wednesday"
    )
    assert result == "RESCHEDULE"


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(days_remaining_in_week=1, monthly_load_pct=70.0, current_week_state="ON_TRACK", reschedule_slot="Wednesday"),
        dict(days_remaining_in_week=3, monthly_load_pct=90.0, current_week_state="ON_TRACK", reschedule_slot="Wednesday"),
        dict(days_remaining_in_week=3, monthly_load_pct=70.0, current_week_state="RECOVERY_WEEK", reschedule_slot="Wednesday"),
        dict(days_remaining_in_week=3, monthly_load_pct=70.0, current_week_state="ON_TRACK", reschedule_slot=None),
    ],
)
def test_write_off_when_any_condition_fails(kwargs):
    assert decide_skip_disposition(**kwargs) == "WRITE_OFF"


# -- apply_skip ---------------------------------------------------------------


def test_apply_skip_reschedules_and_swaps_displaced_session():
    planned = [
        {"day": "Monday", "session_type": "HIIT"},
        {"day": "Wednesday", "session_type": "Zone2_Long"},
    ]
    adapted, record = apply_skip(
        planned,
        skipped_session_type="HIIT",
        skipped_day="Monday",
        days_remaining_in_week=5,
        monthly_load_pct=60.0,
        current_week_state="ON_TRACK",
    )

    assert record["disposition"] == "rescheduled"
    by_day = {s["day"]: s["session_type"] for s in adapted}
    assert by_day["Wednesday"] == "HIIT"
    assert by_day["Monday"] == "Zone2_Long"


def test_apply_skip_writes_off_when_no_valid_slot():
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    planned = [{"day": d, "session_type": "HIIT"} for d in days]
    adapted, record = apply_skip(
        planned,
        skipped_session_type="HIIT",
        skipped_day="Monday",
        days_remaining_in_week=5,
        monthly_load_pct=60.0,
        current_week_state="ON_TRACK",
    )
    assert record["disposition"] == "written_off"


# -- apply_recovery_week_protocol — §4.3 -------------------------------------


def test_recovery_week_protocol_replaces_every_session_type():
    planned = [
        {"day": "Monday", "session_type": "HIIT"},
        {"day": "Tuesday", "session_type": "Threshold"},
        {"day": "Wednesday", "session_type": "Zone2_Long"},
        {"day": "Thursday", "session_type": "Zone2_Short"},
        {"day": "Friday", "session_type": "Strength"},
        {"day": "Saturday", "session_type": "Recovery"},
        {"day": "Sunday", "session_type": "Rest"},
    ]
    replaced = apply_recovery_week_protocol(planned)
    by_day = {s["day"]: s["session_type"] for s in replaced}

    assert by_day["Monday"] == "Zone2_Short"
    assert by_day["Tuesday"] == "Zone2_Short"
    assert by_day["Wednesday"] == "Zone2_Short"
    assert by_day["Thursday"] == "Zone2_Short"
    assert by_day["Friday"] == "Recovery"
    assert by_day["Saturday"] == "Recovery"
    assert by_day["Sunday"] == "Rest"
