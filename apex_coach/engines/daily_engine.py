"""Daily Decision Engine (Logic Spec §3). Pure — no I/O.

Deterministic core; the LLM only explains, never decides (ADR-0001).
Consumes classified inputs from the Orchestrator (Recovery Band, HRV
Delta, Soreness Band) plus session type. See docs/adr/0015 for the
uniform override pre-check, HRV-independent GREEN, Recovery/Rest's
always-GO shape, and the Strength GREEN+HIGH coverage gap.
"""

from enum import StrEnum

from apex_coach.orchestrator.orchestrator import HRVDeltaBand, RecoveryBand, SorenessBand


class DecisionOutput(StrEnum):
    GO = "GO"
    MODIFY = "MODIFY"
    MODALITY_SWAP = "MODALITY_SWAP"
    ABORT = "ABORT"


KEY_SESSION_TYPES = {"HIIT", "Threshold"}
ZONE2_SESSION_TYPES = {"Zone2_Long", "Zone2_Short"}
STRENGTH_SESSION_TYPES = {"Strength"}
RECOVERY_SESSION_TYPES = {"Recovery", "Rest"}

_LOW_SORENESS = {SorenessBand.NONE, SorenessBand.MILD}
_LOW_MOD_SORENESS = {SorenessBand.NONE, SorenessBand.MILD, SorenessBand.MODERATE}


def _decide_key_session(
    recovery_band: RecoveryBand, hrv_signal: HRVDeltaBand, soreness_band: SorenessBand
) -> tuple[DecisionOutput, str | None]:
    """§3.1 — Key Sessions (HIIT & Threshold)."""
    if recovery_band == RecoveryBand.GREEN:
        # GREEN ignores HRV entirely — docs/adr/0015.
        if soreness_band in _LOW_MOD_SORENESS:
            return DecisionOutput.GO, None
        if soreness_band == SorenessBand.HIGH:
            return DecisionOutput.MODIFY, "Reduce interval count by 1. Monitor form carefully."
        return DecisionOutput.ABORT, "Swap to Zone2_Short or Recovery. Do not attempt impact."

    if recovery_band == RecoveryBand.YELLOW:
        if hrv_signal in (HRVDeltaBand.POSITIVE, HRVDeltaBand.NEUTRAL):
            if soreness_band in _LOW_SORENESS:
                return (
                    DecisionOutput.GO,
                    "HRV neutral/positive supports green-equivalent execution.",
                )
            if soreness_band == SorenessBand.MODERATE:
                return (
                    DecisionOutput.MODIFY,
                    "Extend warm-up to 20 min. Cut 1 interval if HR slow to rise.",
                )
            return DecisionOutput.ABORT, "Systemic + local fatigue combined. Protect weekly load."

        if hrv_signal == HRVDeltaBand.NEGATIVE:
            if soreness_band in _LOW_SORENESS:
                return DecisionOutput.MODIFY, (
                    "Extend warm-up 20 min. Abort to Zone2 if HR ceiling not "
                    "reached by interval 2. Watch for cardiac drift."
                )
            return DecisionOutput.ABORT, "HRV negative + soreness elevated. High injury risk."

        # HRV_STRONG_NEG
        return DecisionOutput.ABORT, "Strong HRV suppression overrides yellow band. Treat as red."

    # RED
    return DecisionOutput.ABORT, "Red nervous system. No high-intensity. Swap to Zone2 or Rest."


def _decide_zone2_session(
    recovery_band: RecoveryBand, soreness_band: SorenessBand, session_type: str
) -> tuple[DecisionOutput, str | None]:
    """§3.2 — Zone 2 Sessions. hrv_signal isn't referenced by any branch here."""
    if recovery_band == RecoveryBand.GREEN:
        if soreness_band in _LOW_SORENESS:
            return DecisionOutput.GO, None
        if soreness_band == SorenessBand.MODERATE:
            return DecisionOutput.GO, "Monitor legs. Abort if form breaks down."
        if soreness_band == SorenessBand.HIGH:
            return DecisionOutput.MODALITY_SWAP, (
                "WHOOP green but legs need non-impact. Swap to cycling "
                "or pool running at same Zone 2 HR ceiling."
            )
        return DecisionOutput.ABORT, "Severe soreness. Recovery session only (yoga / foam roll)."

    if recovery_band == RecoveryBand.YELLOW:
        if soreness_band in _LOW_SORENESS:
            return DecisionOutput.GO, "Cap HR at Zone 2 ceiling. No drift upward."
        if soreness_band in (SorenessBand.MODERATE, SorenessBand.HIGH):
            return DecisionOutput.MODALITY_SWAP, (
                "Yellow + soreness. Cycling or swimming Zone 2. "
                "Strict cap: HR must not exceed Zone 2 ceiling."
            )
        return DecisionOutput.ABORT, None

    # RED — branches on session_type only, not soreness.
    if session_type == "Zone2_Short":
        return DecisionOutput.MODIFY, (
            "Strict HR cap at 70% of Zone 2 ceiling. Max 30 min. "
            "Do not allow drift. Consider yoga/foam roll instead."
        )
    return DecisionOutput.ABORT, (
        "Long Zone 2 on red creates more fatigue than adaptation. "
        "Replace with 20-30 min active recovery or full rest."
    )


def _decide_strength_session(
    recovery_band: RecoveryBand, soreness_band: SorenessBand
) -> tuple[DecisionOutput, str | None]:
    """§3.3 — Strength Sessions (joint-pain override handled globally, ADR-0015)."""
    if recovery_band == RecoveryBand.RED or soreness_band == SorenessBand.SEVERE:
        return DecisionOutput.ABORT, "High systemic or mechanical fatigue. Replace with mobility work."

    if recovery_band == RecoveryBand.GREEN:
        if soreness_band in _LOW_SORENESS:
            return DecisionOutput.GO, None
        # MODERATE or HIGH — §3.3 only documents MODERATE; HIGH was an
        # undocumented gap, filled the same way (docs/adr/0015).
        return DecisionOutput.MODIFY, "Reduce working weight by 10-15%. Focus on movement quality."

    # YELLOW
    if soreness_band in _LOW_SORENESS:
        return DecisionOutput.GO, None  # strength less dependent on WHOOP signal
    return DecisionOutput.MODIFY, "Drop to 70% of planned volume. Technique focus session."


def _decide_recovery_session(
    recovery_band: RecoveryBand, hrv_signal: HRVDeltaBand, tomorrow_session_type: str | None
) -> tuple[DecisionOutput, str]:
    """§3.4 — Recovery & Rest Days. Always GO — a rest day cannot be
    upgraded to training; the engine only selects recovery intensity."""
    if recovery_band == RecoveryBand.GREEN:
        protocol = "Standard: 20-30 min yoga or foam rolling."
        if tomorrow_session_type in KEY_SESSION_TYPES:
            protocol += (
                " Add 10 min CNS primer: drills, strides, activation. "
                "Prime without fatigue."
            )
        return DecisionOutput.GO, protocol

    if recovery_band == RecoveryBand.YELLOW:
        if hrv_signal in (HRVDeltaBand.NEUTRAL, HRVDeltaBand.POSITIVE):
            return DecisionOutput.GO, (
                "Parasympathetic flush: 20-30 min yoga + foam rolling. "
                "Nutrition: +10% carbohydrate intake. Sleep gate: +45 min earlier. "
                "Goal: convert yellow to green by tomorrow."
            )
        return DecisionOutput.GO, (
            "Nervous system reboot: NSDR protocol (20 min) or Yoga Nidra. "
            "No physical activity beyond gentle walking. "
            "Nutrition: prioritise protein + anti-inflammatory foods. "
            "Sleep gate: +60 min earlier than usual."
        )

    # RED
    return DecisionOutput.GO, (
        "Full passive rest. No structured activity. "
        "Prioritise sleep, hydration, and nutrition. "
        "Flag to weekly engine: consecutive red days trigger recovery week."
    )


def make_decision(
    session_type: str,
    recovery_band: RecoveryBand,
    hrv_signal: HRVDeltaBand,
    soreness_band: SorenessBand,
    override_triggered: bool = False,
    override_reasons: list[str] | None = None,
    tomorrow_session_type: str | None = None,
) -> dict:
    """Dispatch to the session-type-appropriate decision tree.

    override_triggered short-circuits every tree (docs/adr/0015) — a
    joint-pain flag from health_check.py forces ABORT regardless of
    session type, matching §7.3's "regardless of all other inputs."
    """
    if override_triggered:
        reason = "; ".join(override_reasons) if override_reasons else "health check override"
        return {
            "recommendation": DecisionOutput.ABORT,
            "rationale": f"Joint pain flag. Do not load the flagged structure. ({reason})",
            "check_recovery_week_trigger": False,
        }

    if session_type in KEY_SESSION_TYPES:
        recommendation, rationale = _decide_key_session(recovery_band, hrv_signal, soreness_band)
        check_recovery_week_trigger = recovery_band == RecoveryBand.RED
    elif session_type in ZONE2_SESSION_TYPES:
        recommendation, rationale = _decide_zone2_session(recovery_band, soreness_band, session_type)
        check_recovery_week_trigger = False
    elif session_type in STRENGTH_SESSION_TYPES:
        recommendation, rationale = _decide_strength_session(recovery_band, soreness_band)
        check_recovery_week_trigger = False
    elif session_type in RECOVERY_SESSION_TYPES:
        recommendation, rationale = _decide_recovery_session(
            recovery_band, hrv_signal, tomorrow_session_type
        )
        check_recovery_week_trigger = False
    else:
        raise ValueError(f"unknown session_type: {session_type!r}")

    return {
        "recommendation": recommendation,
        "rationale": rationale,
        "check_recovery_week_trigger": check_recovery_week_trigger,
    }
