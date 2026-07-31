"""Session Load Score (AU) — SDD §5.2, Logic Spec §5.1. Pure — no I/O.

Shared by session_scorer's load_delta_score (F06.1) and monthly_engine's
load accumulation (F08.1) — see docs/adr/0017.

HR-based load (run/ride/swim) uses the Banister Impulse-Response model
(TRIMP), replacing the earlier grade-adjusted approximation — see
docs/adr/0024. TRIMP self-adjusts for terrain via the HR response (climbing
raises HR, which raises the load score directly), so there's no separate
grade term.
"""

import math

HR_BASED_ACTIVITY_TYPES = {"Run", "Ride", "Swim"}
RPE_BASED_ACTIVITY_TYPES = {"WeightTraining"}
DURATION_BASED_ACTIVITY_TYPES = {"Yoga"}

# The original Banister TRIMP research only calibrated this exponential
# weighting constant for two categories — a known simplification inherited
# from the source formula, not a statement about gender more broadly.
TRIMP_B_CONSTANT = {"MALE": 1.92, "FEMALE": 1.67}


def calculate_hr_based_load(
    duration_minutes: float, avg_hr_bpm: float, resting_hr: float, max_hr: float, sex: str
) -> float:
    """Run/ride/swim sessions — Banister TRIMP (docs/adr/0024)."""
    if sex not in TRIMP_B_CONSTANT:
        raise ValueError(f"sex must be one of {sorted(TRIMP_B_CONSTANT)}, got {sex!r}")
    if max_hr <= resting_hr:
        raise ValueError(f"max_hr ({max_hr}) must be greater than resting_hr ({resting_hr})")

    delta_hr_ratio = (avg_hr_bpm - resting_hr) / (max_hr - resting_hr)
    b = TRIMP_B_CONSTANT[sex]
    return duration_minutes * delta_hr_ratio * 0.64 * math.exp(b * delta_hr_ratio)


def calculate_rpe_based_load(duration_minutes: float, rpe: int) -> float:
    """Strength sessions — no HR zone target. RPE 6 for 60 min = 60 AU."""
    return (duration_minutes * rpe) / 6


def calculate_recovery_load(duration_minutes: float) -> float:
    """Recovery sessions (yoga, foam rolling) — minimal training load."""
    return duration_minutes * 0.3


def calculate_load_au(
    activity_type: str,
    duration_minutes: float,
    avg_hr_bpm: float | None = None,
    resting_hr: float | None = None,
    max_hr: float | None = None,
    sex: str | None = None,
    rpe: int | None = None,
) -> float:
    """Dispatches on Strava activity_type (not session_type) — a
    modality-swapped session (e.g. HIIT executed as a bike ride) still
    correctly gets HR-based scoring, matching what physically happened."""
    if activity_type in HR_BASED_ACTIVITY_TYPES:
        missing = [
            name
            for name, value in (
                ("avg_hr_bpm", avg_hr_bpm),
                ("resting_hr", resting_hr),
                ("max_hr", max_hr),
                ("sex", sex),
            )
            if value is None
        ]
        if missing:
            raise ValueError(
                f"{activity_type} requires {', '.join(missing)} for HR-based (TRIMP) load"
            )
        return calculate_hr_based_load(duration_minutes, avg_hr_bpm, resting_hr, max_hr, sex)
    if activity_type in RPE_BASED_ACTIVITY_TYPES:
        if rpe is None:
            raise ValueError(f"{activity_type} requires rpe for RPE-based load")
        return calculate_rpe_based_load(duration_minutes, rpe)
    if activity_type in DURATION_BASED_ACTIVITY_TYPES:
        return calculate_recovery_load(duration_minutes)
    raise ValueError(f"unknown activity_type for load calculation: {activity_type!r}")
