import math

import pytest

from apex_coach.engines.structure_generator import (
    HIIT_REP_RECOVERY_MIN,
    HIIT_REP_WORK_MIN,
    RECOVERY_FIXED_DURATION_MIN,
    STRENGTH_FIXED_DURATION_MIN,
    WARMUP_COOLDOWN_MIN,
    generate_week_structure,
)

MAX_HR, RESTING_HR, SEX = 190, 50, "MALE"

# Independently computed (not derived from the function under test) —
# HRR = 140, zone2 = (134, 148) -> midpoint 141, zone5 = (176, 190) -> midpoint 183.
# ratio_z2 = (141-50)/140 = 0.65; main_set_min for a 100 AU target:
#   100 / (0.65 * 0.64 * e^(1.92*0.65)) = 69.0092259244475
ZONE2_MAIN_SET_MIN_FOR_100_AU = 69.0092259244475

# HIIT rep AU (work=3min@zone5 midpoint 183, recovery=2min@zone2 midpoint 141):
#   ratio_z5 = (183-50)/140 = 0.95; work_au = 3 * 0.95 * 0.64 * e^(1.92*0.95) = 11.302589871796302
#   ratio_z2 = 0.65; recovery_au = 2 * 0.65 * 0.64 * e^(1.92*0.65) = 2.8981632139876985
#   au_per_rep = 14.200753085784001
AU_PER_HIIT_REP = 14.200753085784001


def test_single_zone2_long_day_uses_full_weekly_target_and_inverts_duration():
    planned = [{"day": "Monday", "session_type": "Zone2_Long"}]
    result = generate_week_structure(planned, 100.0, "BASE", MAX_HR, RESTING_HR, SEX)

    assert len(result) == 1
    structure = result[0]["structure"]
    assert structure["type"] == "single_block"
    assert structure["zone"] == "zone2"
    assert structure["target_hr_bpm"] == 141.0
    assert structure["main_set_min"] == pytest.approx(ZONE2_MAIN_SET_MIN_FOR_100_AU)
    assert structure["warmup_cooldown_min"] == WARMUP_COOLDOWN_MIN
    assert structure["total_duration_min"] == pytest.approx(
        ZONE2_MAIN_SET_MIN_FOR_100_AU + WARMUP_COOLDOWN_MIN
    )


def test_single_hiit_day_rounds_rep_count_from_target_au():
    planned = [{"day": "Tuesday", "session_type": "HIIT"}]
    # raw rep count = 50.0 / 14.200753085784001 = 3.52... -> rounds to 4
    result = generate_week_structure(planned, 50.0, "BASE", MAX_HR, RESTING_HR, SEX)

    structure = result[0]["structure"]
    assert structure["type"] == "intervals"
    assert structure["rep_count"] == 4
    assert structure["work_hr_bpm"] == 183.0
    assert structure["recovery_hr_bpm"] == 141.0
    expected_main_set = 4 * (HIIT_REP_WORK_MIN + HIIT_REP_RECOVERY_MIN)
    assert structure["total_duration_min"] == pytest.approx(
        expected_main_set + WARMUP_COOLDOWN_MIN
    )


def test_weekly_target_splits_by_phase_weight_across_present_session_types():
    # BASE weights: HIIT=0.5, Zone2_Long=3.0 -> total 3.5 of a 70 AU week
    # HIIT share = 0.5/3.5 * 70 = 10.0 AU exactly; Zone2_Long = 3.0/3.5 * 70 = 60.0 AU exactly.
    planned = [
        {"day": "Monday", "session_type": "HIIT"},
        {"day": "Tuesday", "session_type": "Zone2_Long"},
    ]
    result = generate_week_structure(planned, 70.0, "BASE", MAX_HR, RESTING_HR, SEX)

    hiit = next(r["structure"] for r in result if r["day"] == "Monday")
    zone2 = next(r["structure"] for r in result if r["day"] == "Tuesday")

    # 10.0 AU / 14.200753085784001 per rep = 0.704... -> rounds to at least 1 rep.
    assert hiit["rep_count"] == 1
    assert zone2["main_set_min"] == pytest.approx(
        60.0 / (0.65 * 0.64 * math.exp(1.92 * 0.65))
    )


def test_strength_session_is_fixed_duration_no_hr_structure():
    planned = [{"day": "Wednesday", "session_type": "Strength"}]
    result = generate_week_structure(planned, 0.0, "BASE", MAX_HR, RESTING_HR, SEX)

    structure = result[0]["structure"]
    assert structure == {"type": "single_block", "duration_min": STRENGTH_FIXED_DURATION_MIN}


def test_recovery_session_is_fixed_duration_at_zone1():
    planned = [{"day": "Thursday", "session_type": "Recovery"}]
    result = generate_week_structure(planned, 0.0, "BASE", MAX_HR, RESTING_HR, SEX)

    structure = result[0]["structure"]
    assert structure == {
        "type": "single_block",
        "zone": "zone1",
        "duration_min": RECOVERY_FIXED_DURATION_MIN,
    }


def test_rest_session_has_zero_duration_no_structure():
    planned = [{"day": "Sunday", "session_type": "Rest"}]
    result = generate_week_structure(planned, 0.0, "BASE", MAX_HR, RESTING_HR, SEX)

    structure = result[0]["structure"]
    assert structure == {"type": "rest", "duration_min": 0.0}


def test_unknown_periodisation_phase_falls_back_to_base_weights():
    planned = [{"day": "Monday", "session_type": "Zone2_Long"}]
    base_result = generate_week_structure(planned, 100.0, "BASE", MAX_HR, RESTING_HR, SEX)
    none_result = generate_week_structure(planned, 100.0, None, MAX_HR, RESTING_HR, SEX)

    assert base_result[0]["structure"] == none_result[0]["structure"]


def test_unknown_session_type_raises():
    planned = [{"day": "Monday", "session_type": "Kayaking"}]
    with pytest.raises(ValueError):
        generate_week_structure(planned, 100.0, "BASE", MAX_HR, RESTING_HR, SEX)
