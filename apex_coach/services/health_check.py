"""Morning Health Check: fixed + adaptive questions (Logic Spec §7).

Pure question-selection and scoring logic — no CLI I/O, no DB access
beyond the explicit persist_health_check() call. See docs/adr/0012 for
scope decisions (no interactive prompt yet, override boolean included,
direction-aware §7.3 override).
"""

import json
from dataclasses import dataclass, field
from typing import Literal

FlagDirection = Literal["high_bad", "low_bad"]

# §7.3's blanket override only applies to "high is bad" (pain/discomfort)
# questions — see docs/adr/0012 for why "low_bad" questions are excluded.
OVERRIDE_THRESHOLD = 4

FIXED_QUESTIONS = (
    ("muscle_soreness", "How is your overall muscle soreness right now?"),
    ("subjective_energy", "How is your subjective energy level today?"),
    ("sleep_quality_felt", "How was your sleep quality last night?"),
)


@dataclass(frozen=True)
class AdaptiveQuestion:
    key: str
    text: str
    # (threshold, flag_name) pairs, ordered most-severe first. The first
    # threshold crossed wins — thresholds are tiers, not cumulative flags.
    flags: tuple[tuple[int, str], ...] = field(default_factory=tuple)
    direction: FlagDirection = "high_bad"


ADAPTIVE_QUESTIONS: dict[str, tuple[AdaptiveQuestion, ...]] = {
    "HIIT": (
        AdaptiveQuestion(
            "left_knee_pain",
            "Left knee pain (1-5)?",
            flags=((4, "ABORT_STRENGTH_RUN"), (3, "MODIFY_NOTE")),
        ),
        AdaptiveQuestion(
            "right_knee_pain",
            "Right knee pain (1-5)?",
            flags=((4, "ABORT_STRENGTH_RUN"), (3, "MODIFY_NOTE")),
        ),
        AdaptiveQuestion(
            "shin_calf_tightness",
            "Shin / calf tightness (1-5)?",
            flags=((4, "ABORT_STRENGTH_RUN"), (3, "MODIFY_NOTE")),
        ),
    ),
    "Threshold": (
        AdaptiveQuestion(
            "left_hamstring_tightness",
            "Left hamstring tightness (1-5)?",
            flags=((4, "ABORT_RUN"), (3, "WARMUP_EXTENSION")),
        ),
        AdaptiveQuestion(
            "right_hamstring_tightness",
            "Right hamstring tightness (1-5)?",
            flags=((4, "ABORT_RUN"), (3, "WARMUP_EXTENSION")),
        ),
        AdaptiveQuestion(
            "achilles_tension",
            "Achilles tension (1-5)?",
            flags=((4, "ABORT_RUN"), (3, "WARMUP_EXTENSION")),
        ),
    ),
    "Zone2_Long": (
        AdaptiveQuestion(
            "left_achilles_pain",
            "Left Achilles pain (1-5)?",
            flags=((3, "MODALITY_SWAP"),),
        ),
        AdaptiveQuestion(
            "right_achilles_pain",
            "Right Achilles pain (1-5)?",
            flags=((3, "MODALITY_SWAP"),),
        ),
        AdaptiveQuestion(
            "leg_fatigue",
            "General leg fatigue (1-5)?",
            flags=((4, "MODIFY"),),
        ),
    ),
    "Zone2_Short": (
        AdaptiveQuestion(
            "leg_fatigue",
            "General leg fatigue (1-5)?",
            flags=((4, "NOTE_LOGGED"),),
        ),
    ),
    "Strength": (
        AdaptiveQuestion(
            "lower_back_tightness",
            "Lower back tightness (1-5)?",
            flags=((4, "ABORT_STRENGTH"), (3, "MODIFY")),
        ),
        AdaptiveQuestion(
            "left_knee_pain",
            "Left knee pain (1-5)?",
            flags=((4, "ABORT_STRENGTH"), (3, "MODIFY")),
        ),
        AdaptiveQuestion(
            "right_knee_pain",
            "Right knee pain (1-5)?",
            flags=((4, "ABORT_STRENGTH"), (3, "MODIFY")),
        ),
    ),
    "Recovery": (
        AdaptiveQuestion(
            "general_wellbeing",
            "General wellbeing (1-5)?",
            flags=((2, "LOW_WELLBEING"),),
            direction="low_bad",
        ),
    ),
    "Rest": (
        AdaptiveQuestion(
            "general_wellbeing",
            "General wellbeing (1-5)?",
            flags=((2, "LOW_WELLBEING"),),
            direction="low_bad",
        ),
    ),
}


def get_adaptive_questions(session_type: str) -> tuple[AdaptiveQuestion, ...]:
    if session_type not in ADAPTIVE_QUESTIONS:
        raise ValueError(f"unknown session type: {session_type!r}")
    return ADAPTIVE_QUESTIONS[session_type]


def _evaluate_flag(question: AdaptiveQuestion, score: int) -> str | None:
    for threshold, flag_name in question.flags:
        if question.direction == "high_bad" and score >= threshold:
            return flag_name
        if question.direction == "low_bad" and score <= threshold:
            return flag_name
    return None


def evaluate_health_check(
    session_type: str,
    fixed_answers: dict[str, int],
    adaptive_answers: dict[str, int],
) -> dict:
    """Score a collected set of answers. Pure — no I/O."""
    questions = get_adaptive_questions(session_type)

    adaptive_results = {}
    override_reasons = []
    for q in questions:
        score = adaptive_answers[q.key]
        flag = _evaluate_flag(q, score)
        adaptive_results[q.key] = {"score": score, "flag": flag}
        if q.direction == "high_bad" and score >= OVERRIDE_THRESHOLD:
            override_reasons.append(f"health_check_override: {q.key} = {score}")

    return {
        "session_type": session_type,
        "fixed_answers": dict(fixed_answers),
        "adaptive_answers": adaptive_results,
        "override_triggered": len(override_reasons) > 0,
        "override_reasons": override_reasons,
    }


def persist_health_check(repo, date: str, result: dict) -> None:
    """Insert or update daily_metrics for `date` — see docs/adr/0012."""
    fields = {
        "muscle_soreness": result["fixed_answers"]["muscle_soreness"],
        "subjective_energy": result["fixed_answers"]["subjective_energy"],
        "sleep_quality_felt": result["fixed_answers"]["sleep_quality_felt"],
        "health_check_json": json.dumps(
            {
                "session_type": result["session_type"],
                "adaptive_answers": result["adaptive_answers"],
                "override_triggered": result["override_triggered"],
                "override_reasons": result["override_reasons"],
            }
        ),
    }

    if repo.get_daily_metrics(date) is None:
        repo.insert_daily_metrics(date=date, **fields)
    else:
        repo.update_daily_metrics(date, **fields)
