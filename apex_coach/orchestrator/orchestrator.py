"""Raw-to-classified translation (ADR-0002, ADR-0013).

Raw floats never enter the decision tree — only their classified
equivalents (Logic Spec §2). This is the one place classification
happens; daily_engine must never see raw WHOOP-shaped data.

Pure — no I/O. hrv_30d_avg_ms is a parameter, not computed here; see
docs/adr/0013 for why that's a separate, not-yet-built concern.
"""

from enum import StrEnum

from apex_coach.models.pydantic_models import WhoopDailyPayload


class RecoveryBand(StrEnum):
    GREEN = "RECOVERY_GREEN"
    YELLOW = "RECOVERY_YELLOW"
    RED = "RECOVERY_RED"


class HRVDeltaBand(StrEnum):
    POSITIVE = "HRV_POSITIVE"
    NEUTRAL = "HRV_NEUTRAL"
    NEGATIVE = "HRV_NEGATIVE"
    STRONG_NEG = "HRV_STRONG_NEG"


class SorenessBand(StrEnum):
    NONE = "SORENESS_NONE"
    MILD = "SORENESS_MILD"
    MODERATE = "SORENESS_MODERATE"
    HIGH = "SORENESS_HIGH"
    SEVERE = "SORENESS_SEVERE"


_SORENESS_BY_SCORE = {
    1: SorenessBand.NONE,
    2: SorenessBand.MILD,
    3: SorenessBand.MODERATE,
    4: SorenessBand.HIGH,
    5: SorenessBand.SEVERE,
}


def classify_recovery(recovery_pct: float) -> RecoveryBand:
    if not (0 <= recovery_pct <= 100):
        raise ValueError(f"recovery_pct must be 0-100, got {recovery_pct!r}")
    if recovery_pct >= 67:
        return RecoveryBand.GREEN
    if recovery_pct >= 34:
        return RecoveryBand.YELLOW
    return RecoveryBand.RED


def classify_hrv_delta(delta_ms: float) -> HRVDeltaBand:
    """See docs/adr/0013 for how the Neutral/Negative boundary at -5 is resolved."""
    if delta_ms > 5:
        return HRVDeltaBand.POSITIVE
    if delta_ms >= -5:
        return HRVDeltaBand.NEUTRAL
    if delta_ms >= -10:
        return HRVDeltaBand.NEGATIVE
    return HRVDeltaBand.STRONG_NEG


def classify_soreness(muscle_soreness: int) -> SorenessBand:
    if muscle_soreness not in _SORENESS_BY_SCORE:
        raise ValueError(f"muscle_soreness must be 1-5, got {muscle_soreness!r}")
    return _SORENESS_BY_SCORE[muscle_soreness]


def classify_daily_inputs(
    whoop_payload: WhoopDailyPayload,
    muscle_soreness: int,
    hrv_30d_avg_ms: float,
) -> dict:
    """Classify a day's raw inputs into the domain bands daily_engine consumes.

    Returns classified enums only — recovery_pct/hrv_delta_ms are included
    for audit/logging, never for decision logic downstream.
    """
    recovery_pct = whoop_payload.whoop_recovery_pct
    if recovery_pct is None:
        raise ValueError("whoop_payload has no recovery score to classify")

    hrv_ms = whoop_payload.whoop_hrv_ms
    if hrv_ms is None:
        raise ValueError("whoop_payload has no HRV reading to classify")
    hrv_delta_ms = hrv_ms - hrv_30d_avg_ms

    return {
        "recovery_band": classify_recovery(recovery_pct),
        "hrv_delta_band": classify_hrv_delta(hrv_delta_ms),
        "soreness_band": classify_soreness(muscle_soreness),
        "recovery_pct": recovery_pct,
        "hrv_delta_ms": hrv_delta_ms,
    }
