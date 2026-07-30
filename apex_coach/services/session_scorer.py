"""Session Execution Scorer (Logic Spec §6).

Scoring logic is pure — no DB access beyond the explicit
persist_session_score() call. Runs after a session syncs from Strava.
Produces execution_score (0-100) and independent overpush/underpush
flags. Never feeds the daily decision engine — purely retrospective
(§6.1). See docs/adr/0014 for the StravaStream/get_activity_stream()
addition and null-component renormalization this ticket introduced.
"""

import json

WARMUP_SECONDS = 600

# Session Type -> intended HR zone (Logic Spec §6.2). Strength has no HR
# target ("RPE only"); Recovery targets Zone 1. Rest is never scored — no
# structured activity exists to sync (§2.4).
INTENDED_ZONE = {
    "HIIT": "zone5",
    "Threshold": "zone4",
    "Zone2_Long": "zone2",
    "Zone2_Short": "zone2",
    "Strength": None,
    "Recovery": "zone1",
}

KEY_SESSION_TYPES = {"HIIT", "Threshold"}
ZONE2_SESSION_TYPES = {"Zone2_Long", "Zone2_Short"}

EXPECTED_RPE = {
    "HIIT": 9,
    "Threshold": 7,
    "Zone2_Long": 4,
    "Zone2_Short": 3,
    "Strength": 6,
    "Recovery": 2,
}

COMPONENT_WEIGHTS = {
    "time_in_zone_score": 0.45,
    "hr_drift_score": 0.25,
    "rpe_alignment_score": 0.20,
    "load_delta_score": 0.10,
}


def score_time_in_zone(
    hr_data: list[float], session_type: str, zone_min: int, zone_max: int
) -> float | None:
    if INTENDED_ZONE.get(session_type) is None:
        return None

    total_seconds = len(hr_data)
    non_warmup_seconds = total_seconds - WARMUP_SECONDS
    if non_warmup_seconds <= 0:
        raise ValueError(
            f"session ({total_seconds}s) is shorter than the {WARMUP_SECONDS}s warm-up"
        )

    in_zone_seconds = sum(
        1
        for hr in hr_data[WARMUP_SECONDS:]
        if zone_min <= hr <= zone_max
    )
    time_in_zone_pct = in_zone_seconds / non_warmup_seconds * 100
    return min(time_in_zone_pct, 100.0)


def compute_hr_drift_ratio(hr_data: list[float]) -> float:
    """Raw cardiac decoupling coefficient — persisted separately as
    session_scores.hr_drift_coeff, distinct from the tiered hr_drift_score."""
    midpoint = len(hr_data) // 2
    first_half_avg = sum(hr_data[:midpoint]) / midpoint
    second_half_avg = sum(hr_data[midpoint:]) / (len(hr_data) - midpoint)
    return (second_half_avg - first_half_avg) / first_half_avg


def score_hr_drift(hr_data: list[float], session_type: str) -> float | None:
    if session_type in KEY_SESSION_TYPES:
        return 80.0  # fatigue accumulation is the goal — not penalised
    if session_type not in ZONE2_SESSION_TYPES:
        # Strength isn't HR-paced; Recovery/Rest have no aerobic-decoupling
        # concept (§6.2 only defines mappings for Zone 2 and KEY sessions).
        return None

    drift_ratio = compute_hr_drift_ratio(hr_data)
    if drift_ratio <= 0.03:
        return 100.0
    if drift_ratio <= 0.05:
        return 85.0
    if drift_ratio <= 0.08:
        return 70.0
    if drift_ratio <= 0.12:
        return 50.0
    return 30.0


def score_rpe_alignment(session_type: str, actual_rpe: int) -> float:
    expected_rpe = EXPECTED_RPE[session_type]
    rpe_delta = abs(actual_rpe - expected_rpe)
    if rpe_delta == 0:
        return 100.0
    if rpe_delta == 1:
        return 85.0
    if rpe_delta == 2:
        return 65.0
    if rpe_delta == 3:
        return 40.0
    return 15.0


def score_load_delta(actual_load_au: float, planned_load_au: float) -> float:
    load_delta_ratio = abs(actual_load_au - planned_load_au) / planned_load_au
    if load_delta_ratio <= 0.05:
        return 100.0
    if load_delta_ratio <= 0.10:
        return 90.0
    if load_delta_ratio <= 0.20:
        return 75.0
    if load_delta_ratio <= 0.35:
        return 55.0
    return 30.0


def compute_execution_score(components: dict[str, float | None]) -> float:
    """Weighted sum, renormalized over whichever components apply
    (docs/adr/0014) — None components are excluded, not zeroed."""
    applicable_weight = sum(
        COMPONENT_WEIGHTS[name]
        for name, value in components.items()
        if value is not None
    )
    if applicable_weight == 0:
        raise ValueError("no applicable scoring components")

    return sum(
        value * (COMPONENT_WEIGHTS[name] / applicable_weight)
        for name, value in components.items()
        if value is not None
    )


def detect_overpush(
    hr_data: list[float], session_type: str, zone_max: int
) -> bool:
    if session_type == "Threshold":
        threshold_pct = 0.15
    elif session_type in ZONE2_SESSION_TYPES:
        threshold_pct = 0.10
    else:
        return False

    over_seconds = sum(1 for hr in hr_data if hr > zone_max)
    return (over_seconds / len(hr_data)) > threshold_pct


def detect_underpush(
    hr_data: list[float], session_type: str, zone_min: int, zone_max: int
) -> bool:
    if session_type == "HIIT":
        non_warmup = hr_data[WARMUP_SECONDS:]
        if not non_warmup:
            raise ValueError(
                f"session ({len(hr_data)}s) is shorter than the {WARMUP_SECONDS}s warm-up"
            )
        under_seconds = sum(1 for hr in non_warmup if hr < zone_max)
        return (under_seconds / len(non_warmup)) > 0.40

    if session_type == "Threshold":
        avg_hr = sum(hr_data) / len(hr_data)
        return avg_hr < zone_min

    return False


def score_session(
    session_type: str,
    hr_data: list[float],
    zone_boundaries: dict[str, tuple[int, int]] | None,
    actual_rpe: int,
    actual_load_au: float,
    planned_load_au: float,
) -> dict:
    """Score a completed session. Pure — caller supplies stream data and
    resolved zone boundaries (from zone_calculator), no DB/adapter access.
    """
    intended_zone_key = INTENDED_ZONE.get(session_type)
    if intended_zone_key is not None:
        zone_min, zone_max = zone_boundaries[intended_zone_key]
        time_in_zone_score = score_time_in_zone(hr_data, session_type, zone_min, zone_max)
    else:
        time_in_zone_score = None

    hr_drift_score = score_hr_drift(hr_data, session_type)
    hr_drift_ratio = compute_hr_drift_ratio(hr_data) if hr_drift_score is not None else None

    components = {
        "time_in_zone_score": time_in_zone_score,
        "hr_drift_score": hr_drift_score,
        "rpe_alignment_score": score_rpe_alignment(session_type, actual_rpe),
        "load_delta_score": score_load_delta(actual_load_au, planned_load_au),
    }
    execution_score = compute_execution_score(components)

    if session_type in ("Threshold", *ZONE2_SESSION_TYPES):
        zone_key = INTENDED_ZONE[session_type]
        _, zone_max = zone_boundaries[zone_key]
        overpush_flag = detect_overpush(hr_data, session_type, zone_max)
    else:
        overpush_flag = False

    if session_type in ("HIIT", "Threshold"):
        # §6.3 checks both against zone4's boundaries — HIIT's own intended
        # zone is zone5, but "HR < zone4_max" is how the spec defines
        # "never reached zone5" (zone5_min == zone4_max, adjacent zones).
        zone4_min, zone4_max = zone_boundaries["zone4"]
        underpush_flag = detect_underpush(hr_data, session_type, zone4_min, zone4_max)
    else:
        underpush_flag = False

    return {
        "execution_score": execution_score,
        "time_in_zone_pct": time_in_zone_score,
        "hr_drift_coeff": hr_drift_ratio,
        "overpush_flag": overpush_flag,
        "underpush_flag": underpush_flag,
        "score_breakdown": components,
    }


def persist_session_score(repo, activity_id: str, result: dict) -> str:
    """Insert into session_scores — append-only, one row per scoring run
    (ADR-0006). Returns the new row's id."""
    return repo.insert_session_score(
        activity_id=activity_id,
        execution_score=result["execution_score"],
        time_in_zone_pct=result["time_in_zone_pct"],
        hr_drift_coeff=result["hr_drift_coeff"],
        overpush_flag=result["overpush_flag"],
        underpush_flag=result["underpush_flag"],
        score_breakdown_json=json.dumps(result["score_breakdown"]),
    )
