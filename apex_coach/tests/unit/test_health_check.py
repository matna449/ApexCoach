import pytest

from apex_coach.services.health_check import (
    ADAPTIVE_QUESTIONS,
    evaluate_health_check,
    get_adaptive_questions,
)

FIXED_ANSWERS = {
    "muscle_soreness": 2,
    "subjective_energy": 4,
    "sleep_quality_felt": 4,
}


@pytest.mark.parametrize("session_type", list(ADAPTIVE_QUESTIONS.keys()))
def test_get_adaptive_questions_returns_questions_for_every_documented_session_type(
    session_type,
):
    questions = get_adaptive_questions(session_type)
    assert len(questions) >= 1


def test_get_adaptive_questions_rejects_unknown_session_type():
    with pytest.raises(ValueError):
        get_adaptive_questions("Yoga")


def test_hiit_questions_match_logic_spec_7_2():
    questions = get_adaptive_questions("HIIT")
    keys = {q.key for q in questions}
    assert keys == {"left_knee_pain", "right_knee_pain", "shin_calf_tightness"}


def test_zone2_long_has_per_question_thresholds_not_uniform():
    questions = {q.key: q for q in get_adaptive_questions("Zone2_Long")}
    # Achilles flags at 3 (MODALITY_SWAP); leg fatigue only flags at 4 (MODIFY)
    # — different thresholds within the same session type.
    assert questions["left_achilles_pain"].flags == ((3, "MODALITY_SWAP"),)
    assert questions["leg_fatigue"].flags == ((4, "MODIFY"),)


def test_recovery_wellbeing_is_inverted_direction():
    questions = get_adaptive_questions("Recovery")
    assert questions[0].direction == "low_bad"


# -- evaluate_health_check --------------------------------------------------


def test_hiit_score_of_4_triggers_abort_flag_and_override():
    result = evaluate_health_check(
        "HIIT", FIXED_ANSWERS, {"left_knee_pain": 4, "right_knee_pain": 1, "shin_calf_tightness": 1}
    )

    assert result["adaptive_answers"]["left_knee_pain"]["flag"] == "ABORT_STRENGTH_RUN"
    assert result["override_triggered"] is True
    assert "health_check_override: left_knee_pain = 4" in result["override_reasons"]


def test_hiit_score_of_3_triggers_modify_note_not_override():
    result = evaluate_health_check(
        "HIIT", FIXED_ANSWERS, {"left_knee_pain": 3, "right_knee_pain": 1, "shin_calf_tightness": 1}
    )

    assert result["adaptive_answers"]["left_knee_pain"]["flag"] == "MODIFY_NOTE"
    assert result["override_triggered"] is False


def test_hiit_score_of_2_triggers_no_flag():
    result = evaluate_health_check(
        "HIIT", FIXED_ANSWERS, {"left_knee_pain": 2, "right_knee_pain": 1, "shin_calf_tightness": 1}
    )

    assert result["adaptive_answers"]["left_knee_pain"]["flag"] is None
    assert result["override_triggered"] is False


def test_zone2_long_achilles_3_flags_modality_swap_without_override():
    result = evaluate_health_check(
        "Zone2_Long",
        FIXED_ANSWERS,
        {"left_achilles_pain": 3, "right_achilles_pain": 1, "leg_fatigue": 1},
    )

    assert result["adaptive_answers"]["left_achilles_pain"]["flag"] == "MODALITY_SWAP"
    # 3 is below the high_bad override threshold (4) — no FORCE ABORT trigger.
    assert result["override_triggered"] is False


def test_recovery_wellbeing_5_does_not_trigger_override_despite_being_ge_4():
    """The §7.3 override is direction-aware (docs/adr/0012) — a great
    wellbeing score must never look like a pain-scale safety trigger."""
    result = evaluate_health_check("Recovery", FIXED_ANSWERS, {"general_wellbeing": 5})

    assert result["override_triggered"] is False
    assert result["adaptive_answers"]["general_wellbeing"]["flag"] is None


def test_recovery_wellbeing_low_score_flags_low_wellbeing():
    result = evaluate_health_check("Recovery", FIXED_ANSWERS, {"general_wellbeing": 2})

    assert result["adaptive_answers"]["general_wellbeing"]["flag"] == "LOW_WELLBEING"
    assert result["override_triggered"] is False


def test_multiple_high_scores_produce_multiple_override_reasons():
    result = evaluate_health_check(
        "Strength",
        FIXED_ANSWERS,
        {"lower_back_tightness": 4, "left_knee_pain": 4, "right_knee_pain": 1},
    )

    assert len(result["override_reasons"]) == 2


def test_fixed_answers_are_passed_through_unchanged():
    result = evaluate_health_check("Rest", FIXED_ANSWERS, {"general_wellbeing": 4})

    assert result["fixed_answers"] == FIXED_ANSWERS
