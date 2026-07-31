"""Session Load Score (AU) — SDD §5.2, Logic Spec §5.1. Pure — no I/O.

Shared by session_scorer's load_delta_score (F06.1, activities.load_score
still unpopulated) and monthly_engine's load accumulation (F08.1) — see
docs/adr/0017.
"""

HR_BASED_ACTIVITY_TYPES = {"Run", "Ride", "Swim"}
RPE_BASED_ACTIVITY_TYPES = {"WeightTraining"}
DURATION_BASED_ACTIVITY_TYPES = {"Yoga"}


def grade_adjustment_factor(grade_pct: float) -> float:
    if grade_pct <= 0:
        return 1.00
    if grade_pct <= 3:
        return 1.05
    if grade_pct <= 6:
        return 1.12
    if grade_pct <= 10:
        return 1.22
    return 1.35


def calculate_hr_based_load(duration_minutes: float, avg_hr_bpm: float, grade_pct: float) -> float:
    """Run/ride/swim sessions."""
    return (duration_minutes * avg_hr_bpm * grade_adjustment_factor(grade_pct)) / 1000


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
    grade_pct: float = 0.0,
    rpe: int | None = None,
) -> float:
    """Dispatches on Strava activity_type (not session_type) — a
    modality-swapped session (e.g. HIIT executed as a bike ride) still
    correctly gets HR-based scoring, matching what physically happened."""
    if activity_type in HR_BASED_ACTIVITY_TYPES:
        if avg_hr_bpm is None:
            raise ValueError(f"{activity_type} requires avg_hr_bpm for HR-based load")
        return calculate_hr_based_load(duration_minutes, avg_hr_bpm, grade_pct)
    if activity_type in RPE_BASED_ACTIVITY_TYPES:
        if rpe is None:
            raise ValueError(f"{activity_type} requires rpe for RPE-based load")
        return calculate_rpe_based_load(duration_minutes, rpe)
    if activity_type in DURATION_BASED_ACTIVITY_TYPES:
        return calculate_recovery_load(duration_minutes)
    raise ValueError(f"unknown activity_type for load calculation: {activity_type!r}")
