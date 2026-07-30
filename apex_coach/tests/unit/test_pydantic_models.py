import pytest
from pydantic import ValidationError

from apex_coach.models.pydantic_models import WhoopRecovery


def test_whoop_recovery_accepts_scored_state():
    recovery = WhoopRecovery(
        cycle_id=1,
        created_at="2026-07-30T06:00:00.000Z",
        score_state="SCORED",
        score={
            "recovery_score": 62.0,
            "resting_heart_rate": 48.0,
            "hrv_rmssd_milli": 71.4,
        },
    )
    assert recovery.score.recovery_score == 62.0


def test_whoop_recovery_rejects_pending_score():
    with pytest.raises(ValidationError):
        WhoopRecovery(
            cycle_id=1,
            created_at="2026-07-30T06:00:00.000Z",
            score_state="PENDING_SCORE",
        )
