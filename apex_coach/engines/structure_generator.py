"""Turns a planned week (day -> session_type) into a full structured HR-zone
breakdown per day — PRD #111, docs/adr/0027. Pure — no I/O. Mirrors the
functional-core pattern in monthly_engine.py/load_calculator.py.

Session-type handling (grill-me interview, see PRD #111):
- HIIT/Threshold/Zone2_Long/Zone2_Short: AU-target derived from the weekly
  load target, split via PHASE_SESSION_TYPE_WEIGHTS, then TRIMP-inverted
  (or rep-counted for HIIT) into a duration at a fixed zone-midpoint HR.
- Strength/Recovery/Rest: fixed-duration blocks, no TRIMP inversion
  (Strength is RPE-based; Recovery/Rest are degenerate at Z1).
"""

from apex_coach.services.load_calculator import (
    calculate_hr_based_load,
    invert_duration_for_target_load,
)
from apex_coach.services.zone_calculator import calculate_zones, zone_midpoint

# Fixed constants — tunable v1 defaults, same treatment as TRIMP_B_CONSTANT.
WARMUP_COOLDOWN_MIN = 10.0
HIIT_REP_WORK_MIN = 3.0
HIIT_REP_RECOVERY_MIN = 2.0
STRENGTH_FIXED_DURATION_MIN = 45.0
RECOVERY_FIXED_DURATION_MIN = 30.0
REST_FIXED_DURATION_MIN = 0.0

HIIT_RECOVERY_ZONE = "zone2"

SESSION_TYPE_ZONE = {
    "HIIT": "zone5",
    "Threshold": "zone4",
    "Zone2_Long": "zone2",
    "Zone2_Short": "zone2",
}

AU_DISTRIBUTED_SESSION_TYPES = set(SESSION_TYPE_ZONE)

# Relative weight per session type within each periodisation phase — not
# evidence-derived, a tunable v1 default. Normalized at runtime across
# whichever AU-distributed types actually appear in a given week's plan.
PHASE_SESSION_TYPE_WEIGHTS = {
    "BASE": {"HIIT": 0.5, "Threshold": 1.0, "Zone2_Long": 3.0, "Zone2_Short": 2.0},
    "BUILD": {"HIIT": 1.5, "Threshold": 2.0, "Zone2_Long": 2.5, "Zone2_Short": 1.5},
    "PEAK": {"HIIT": 2.5, "Threshold": 2.5, "Zone2_Long": 1.5, "Zone2_Short": 1.0},
    "TAPER": {"HIIT": 1.0, "Threshold": 1.0, "Zone2_Long": 1.0, "Zone2_Short": 1.0},
    "RECOVERY": {"HIIT": 0.5, "Threshold": 0.5, "Zone2_Long": 1.0, "Zone2_Short": 2.0},
}


def generate_week_structure(
    planned_sessions: list[dict],
    weekly_load_target: float,
    periodisation_phase: str | None,
    max_hr: int,
    resting_hr: int,
    sex: str,
) -> list[dict]:
    """Returns one entry per planned_sessions day:
    {"day": ..., "session_type": ..., "structure": {...}}."""
    zones = calculate_zones(max_hr, resting_hr)
    weights = PHASE_SESSION_TYPE_WEIGHTS.get(periodisation_phase, PHASE_SESSION_TYPE_WEIGHTS["BASE"])

    total_weight = sum(
        weights[s["session_type"]]
        for s in planned_sessions
        if s["session_type"] in AU_DISTRIBUTED_SESSION_TYPES
    )

    structured = []
    for session in planned_sessions:
        session_type = session["session_type"]

        if session_type in AU_DISTRIBUTED_SESSION_TYPES:
            share = weights[session_type] / total_weight if total_weight else 0.0
            session_target_au = weekly_load_target * share
            if session_type == "HIIT":
                structure = _hiit_structure(session_target_au, zones, resting_hr, max_hr, sex)
            else:
                structure = _single_block_hr_structure(
                    session_type, session_target_au, zones, resting_hr, max_hr, sex
                )
        elif session_type == "Strength":
            structure = {"type": "single_block", "duration_min": STRENGTH_FIXED_DURATION_MIN}
        elif session_type == "Recovery":
            structure = {
                "type": "single_block",
                "zone": "zone1",
                "duration_min": RECOVERY_FIXED_DURATION_MIN,
            }
        elif session_type == "Rest":
            structure = {"type": "rest", "duration_min": REST_FIXED_DURATION_MIN}
        else:
            raise ValueError(f"unknown session_type: {session_type!r}")

        structured.append(
            {"day": session["day"], "session_type": session_type, "structure": structure}
        )

    return structured


def _single_block_hr_structure(session_type, session_target_au, zones, resting_hr, max_hr, sex):
    zone_name = SESSION_TYPE_ZONE[session_type]
    target_hr = zone_midpoint(zones[zone_name])
    main_set_min = invert_duration_for_target_load(
        session_target_au, target_hr, resting_hr, max_hr, sex
    )
    return {
        "type": "single_block",
        "zone": zone_name,
        "target_hr_bpm": target_hr,
        "main_set_min": main_set_min,
        "warmup_cooldown_min": WARMUP_COOLDOWN_MIN,
        "total_duration_min": main_set_min + WARMUP_COOLDOWN_MIN,
    }


def _hiit_structure(session_target_au, zones, resting_hr, max_hr, sex):
    work_hr = zone_midpoint(zones["zone5"])
    recovery_hr = zone_midpoint(zones[HIIT_RECOVERY_ZONE])

    work_au = calculate_hr_based_load(HIIT_REP_WORK_MIN, work_hr, resting_hr, max_hr, sex)
    recovery_au = calculate_hr_based_load(HIIT_REP_RECOVERY_MIN, recovery_hr, resting_hr, max_hr, sex)
    au_per_rep = work_au + recovery_au

    rep_count = max(1, round(session_target_au / au_per_rep)) if au_per_rep else 1
    main_set_min = rep_count * (HIIT_REP_WORK_MIN + HIIT_REP_RECOVERY_MIN)

    return {
        "type": "intervals",
        "rep_count": rep_count,
        "work_zone": "zone5",
        "work_hr_bpm": work_hr,
        "work_min": HIIT_REP_WORK_MIN,
        "recovery_zone": HIIT_RECOVERY_ZONE,
        "recovery_hr_bpm": recovery_hr,
        "recovery_min": HIIT_REP_RECOVERY_MIN,
        "warmup_cooldown_min": WARMUP_COOLDOWN_MIN,
        "total_duration_min": main_set_min + WARMUP_COOLDOWN_MIN,
    }
