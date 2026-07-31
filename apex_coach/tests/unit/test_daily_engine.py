import itertools

import pytest

from apex_coach.engines.daily_engine import (
    KEY_SESSION_TYPES,
    RECOVERY_SESSION_TYPES,
    STRENGTH_SESSION_TYPES,
    ZONE2_SESSION_TYPES,
    DecisionOutput,
    make_decision,
)
from apex_coach.orchestrator.orchestrator import HRVDeltaBand, RecoveryBand, SorenessBand

GREEN, YELLOW, RED = RecoveryBand.GREEN, RecoveryBand.YELLOW, RecoveryBand.RED
POS, NEU, NEG, SNEG = (
    HRVDeltaBand.POSITIVE,
    HRVDeltaBand.NEUTRAL,
    HRVDeltaBand.NEGATIVE,
    HRVDeltaBand.STRONG_NEG,
)
NONE_, MILD, MOD, HIGH, SEV = (
    SorenessBand.NONE,
    SorenessBand.MILD,
    SorenessBand.MODERATE,
    SorenessBand.HIGH,
    SorenessBand.SEVERE,
)
GO, MODIFY, SWAP, ABORT = (
    DecisionOutput.GO,
    DecisionOutput.MODIFY,
    DecisionOutput.MODALITY_SWAP,
    DecisionOutput.ABORT,
)


def decide(session_type, recovery, hrv, soreness, **kwargs):
    return make_decision(session_type, recovery, hrv, soreness, **kwargs)


# -- Override pre-check (docs/adr/0015) — supersedes every tree ------------


@pytest.mark.parametrize(
    "session_type", ["HIIT", "Threshold", "Zone2_Long", "Zone2_Short", "Strength", "Recovery", "Rest"]
)
def test_override_triggered_forces_abort_regardless_of_session_type(session_type):
    result = decide(
        session_type,
        GREEN,
        POS,
        NONE_,
        override_triggered=True,
        override_reasons=["health_check_override: left_knee_pain = 4"],
    )
    assert result["recommendation"] == ABORT
    assert "left_knee_pain = 4" in result["rationale"]
    assert result["check_recovery_week_trigger"] is False


def test_override_not_triggered_runs_normal_tree():
    result = decide("HIIT", GREEN, POS, NONE_, override_triggered=False)
    assert result["recommendation"] == GO


def test_unknown_session_type_raises():
    with pytest.raises(ValueError):
        decide("Yoga", GREEN, POS, NONE_)


# -- §3.1 Key Sessions (HIIT & Threshold) ------------------------------------


@pytest.mark.parametrize("session_type", ["HIIT", "Threshold"])
@pytest.mark.parametrize("soreness", [NONE_, MILD, MOD])
def test_key_green_low_to_moderate_soreness_goes(session_type, soreness):
    result = decide(session_type, GREEN, NEG, soreness)  # HRV ignored for GREEN
    assert result["recommendation"] == GO
    assert result["rationale"] is None


def test_key_green_high_soreness_modifies():
    result = decide("HIIT", GREEN, SNEG, HIGH)  # HRV still ignored
    assert result["recommendation"] == MODIFY
    assert result["rationale"] == "Reduce interval count by 1. Monitor form carefully."


def test_key_green_severe_soreness_aborts():
    result = decide("Threshold", GREEN, POS, SEV)
    assert result["recommendation"] == ABORT
    assert result["rationale"] == "Swap to Zone2_Short or Recovery. Do not attempt impact."


@pytest.mark.parametrize("hrv", [POS, NEU])
def test_key_yellow_positive_neutral_low_soreness_goes(hrv):
    result = decide("HIIT", YELLOW, hrv, MILD)
    assert result["recommendation"] == GO
    assert result["rationale"] == "HRV neutral/positive supports green-equivalent execution."


@pytest.mark.parametrize("hrv", [POS, NEU])
def test_key_yellow_positive_neutral_moderate_soreness_modifies(hrv):
    result = decide("Threshold", YELLOW, hrv, MOD)
    assert result["recommendation"] == MODIFY
    assert result["rationale"] == "Extend warm-up to 20 min. Cut 1 interval if HR slow to rise."


@pytest.mark.parametrize("hrv", [POS, NEU])
@pytest.mark.parametrize("soreness", [HIGH, SEV])
def test_key_yellow_positive_neutral_high_severe_soreness_aborts(hrv, soreness):
    result = decide("HIIT", YELLOW, hrv, soreness)
    assert result["recommendation"] == ABORT
    assert result["rationale"] == "Systemic + local fatigue combined. Protect weekly load."


def test_key_yellow_negative_low_soreness_modifies():
    result = decide("Threshold", YELLOW, NEG, NONE_)
    assert result["recommendation"] == MODIFY
    assert "cardiac drift" in result["rationale"]


@pytest.mark.parametrize("soreness", [MOD, HIGH, SEV])
def test_key_yellow_negative_moderate_plus_soreness_aborts(soreness):
    result = decide("HIIT", YELLOW, NEG, soreness)
    assert result["recommendation"] == ABORT
    assert result["rationale"] == "HRV negative + soreness elevated. High injury risk."


@pytest.mark.parametrize("soreness", [NONE_, MILD, MOD, HIGH, SEV])
def test_key_yellow_strong_neg_always_aborts(soreness):
    result = decide("Threshold", YELLOW, SNEG, soreness)
    assert result["recommendation"] == ABORT
    assert result["rationale"] == "Strong HRV suppression overrides yellow band. Treat as red."


@pytest.mark.parametrize("hrv", [POS, NEU, NEG, SNEG])
@pytest.mark.parametrize("soreness", [NONE_, MILD, MOD, HIGH, SEV])
def test_key_red_always_aborts_and_flags_recovery_week(hrv, soreness):
    result = decide("HIIT", RED, hrv, soreness)
    assert result["recommendation"] == ABORT
    assert result["rationale"] == "Red nervous system. No high-intensity. Swap to Zone2 or Rest."
    assert result["check_recovery_week_trigger"] is True


def test_key_recovery_week_trigger_only_set_for_red():
    assert decide("HIIT", GREEN, POS, NONE_)["check_recovery_week_trigger"] is False
    assert decide("HIIT", YELLOW, SNEG, SEV)["check_recovery_week_trigger"] is False


# -- §3.2 Zone 2 Sessions -----------------------------------------------------


@pytest.mark.parametrize("session_type", ["Zone2_Long", "Zone2_Short"])
@pytest.mark.parametrize("soreness", [NONE_, MILD])
def test_zone2_green_low_soreness_goes(session_type, soreness):
    result = decide(session_type, GREEN, NEU, soreness)
    assert result["recommendation"] == GO
    assert result["rationale"] is None


def test_zone2_green_moderate_soreness_goes_with_modifier():
    result = decide("Zone2_Long", GREEN, NEU, MOD)
    assert result["recommendation"] == GO
    assert result["rationale"] == "Monitor legs. Abort if form breaks down."


def test_zone2_green_high_soreness_modality_swaps():
    result = decide("Zone2_Short", GREEN, NEU, HIGH)
    assert result["recommendation"] == SWAP
    assert "non-impact" in result["rationale"]


def test_zone2_green_severe_soreness_aborts():
    result = decide("Zone2_Long", GREEN, NEU, SEV)
    assert result["recommendation"] == ABORT
    assert result["rationale"] == "Severe soreness. Recovery session only (yoga / foam roll)."


def test_zone2_yellow_low_soreness_goes_with_cap():
    result = decide("Zone2_Short", YELLOW, NEU, MILD)
    assert result["recommendation"] == GO
    assert result["rationale"] == "Cap HR at Zone 2 ceiling. No drift upward."


@pytest.mark.parametrize("soreness", [MOD, HIGH])
def test_zone2_yellow_moderate_high_soreness_modality_swaps(soreness):
    result = decide("Zone2_Long", YELLOW, NEU, soreness)
    assert result["recommendation"] == SWAP
    assert "Strict cap" in result["rationale"]


def test_zone2_yellow_severe_soreness_aborts_no_modifier():
    result = decide("Zone2_Short", YELLOW, NEU, SEV)
    assert result["recommendation"] == ABORT
    assert result["rationale"] is None


def test_zone2_short_red_modifies_with_strict_cap():
    result = decide("Zone2_Short", RED, NEU, MOD)
    assert result["recommendation"] == MODIFY
    assert "70% of Zone 2 ceiling" in result["rationale"]


def test_zone2_long_red_aborts():
    result = decide("Zone2_Long", RED, NEU, MOD)
    assert result["recommendation"] == ABORT
    assert "more fatigue than adaptation" in result["rationale"]


# -- §3.3 Strength Sessions ---------------------------------------------------


@pytest.mark.parametrize("soreness", [NONE_, MILD])
def test_strength_green_low_soreness_goes(soreness):
    result = decide("Strength", GREEN, NEU, soreness)
    assert result["recommendation"] == GO
    assert result["rationale"] is None


def test_strength_green_moderate_soreness_modifies():
    result = decide("Strength", GREEN, NEU, MOD)
    assert result["recommendation"] == MODIFY
    assert result["rationale"] == "Reduce working weight by 10-15%. Focus on movement quality."


def test_strength_green_high_soreness_modifies_same_as_moderate():
    """§3.3 leaves GREEN+HIGH undocumented — filled per docs/adr/0015."""
    result = decide("Strength", GREEN, NEU, HIGH)
    assert result["recommendation"] == MODIFY
    assert result["rationale"] == "Reduce working weight by 10-15%. Focus on movement quality."


@pytest.mark.parametrize("soreness", [NONE_, MILD])
def test_strength_yellow_low_soreness_goes(soreness):
    result = decide("Strength", YELLOW, NEU, soreness)
    assert result["recommendation"] == GO


@pytest.mark.parametrize("soreness", [MOD, HIGH])
def test_strength_yellow_moderate_high_soreness_modifies(soreness):
    result = decide("Strength", YELLOW, NEU, soreness)
    assert result["recommendation"] == MODIFY
    assert result["rationale"] == "Drop to 70% of planned volume. Technique focus session."


def test_strength_red_always_aborts():
    result = decide("Strength", RED, NEU, NONE_)
    assert result["recommendation"] == ABORT
    assert result["rationale"] == "High systemic or mechanical fatigue. Replace with mobility work."


def test_strength_severe_soreness_always_aborts_regardless_of_recovery():
    result = decide("Strength", GREEN, NEU, SEV)
    assert result["recommendation"] == ABORT


# -- §3.4 Recovery & Rest Days ------------------------------------------------


@pytest.mark.parametrize("session_type", ["Recovery", "Rest"])
def test_recovery_green_no_key_tomorrow_standard_protocol(session_type):
    result = decide(session_type, GREEN, NEU, NONE_, tomorrow_session_type="Zone2_Long")
    assert result["recommendation"] == GO
    assert result["rationale"] == "Standard: 20-30 min yoga or foam rolling."


@pytest.mark.parametrize("tomorrow", ["HIIT", "Threshold"])
def test_recovery_green_key_tomorrow_adds_primer(tomorrow):
    result = decide("Recovery", GREEN, NEU, NONE_, tomorrow_session_type=tomorrow)
    assert result["recommendation"] == GO
    assert "CNS primer" in result["rationale"]


@pytest.mark.parametrize("hrv", [NEU, POS])
def test_recovery_yellow_neutral_positive_hrv_parasympathetic_flush(hrv):
    result = decide("Recovery", YELLOW, hrv, NONE_)
    assert result["recommendation"] == GO
    assert "Parasympathetic flush" in result["rationale"]


@pytest.mark.parametrize("hrv", [NEG, SNEG])
def test_recovery_yellow_negative_hrv_nervous_system_reboot(hrv):
    result = decide("Rest", YELLOW, hrv, NONE_)
    assert result["recommendation"] == GO
    assert "Nervous system reboot" in result["rationale"]


def test_recovery_red_full_passive_rest():
    result = decide("Rest", RED, NEU, NONE_)
    assert result["recommendation"] == GO
    assert "Full passive rest" in result["rationale"]


def test_recovery_never_produces_non_go_recommendation():
    for recovery in (GREEN, YELLOW, RED):
        for hrv in (POS, NEU, NEG, SNEG):
            result = decide("Recovery", recovery, hrv, SEV)
            assert result["recommendation"] == GO


# -- Full matrix smoke test (SDD's documented test strategy) ---------------


ALL_SESSION_TYPES = (
    list(KEY_SESSION_TYPES)
    + list(ZONE2_SESSION_TYPES)
    + list(STRENGTH_SESSION_TYPES)
    + list(RECOVERY_SESSION_TYPES)
)


@pytest.mark.parametrize(
    "session_type, recovery, hrv, soreness",
    list(
        itertools.product(
            ALL_SESSION_TYPES,
            (GREEN, YELLOW, RED),
            (POS, NEU, NEG, SNEG),
            (NONE_, MILD, MOD, HIGH, SEV),
        )
    ),
)
def test_full_matrix_never_crashes_and_always_returns_valid_decision(
    session_type, recovery, hrv, soreness
):
    result = decide(session_type, recovery, hrv, soreness, tomorrow_session_type="Zone2_Long")

    assert result["recommendation"] in DecisionOutput
    assert result["rationale"] is None or isinstance(result["rationale"], str)
    assert isinstance(result["check_recovery_week_trigger"], bool)
