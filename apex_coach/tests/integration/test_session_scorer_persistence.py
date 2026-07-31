import json

import pytest

from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.schema import metadata
from apex_coach.services.session_scorer import persist_session_score, score_session


@pytest.fixture
def repo():
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    return MetricsRepository(engine)


def test_persist_session_score_writes_full_breakdown(repo):
    repo.insert_daily_metrics(date="2026-07-30")
    repo.save_activity(strava_id="strava-1", date="2026-07-30")
    activity_id = repo.get_activity("strava-1")["id"]

    hr_data = [110.0] * 600 + [165.0] * 2647
    result = score_session(
        session_type="Threshold",
        hr_data=hr_data,
        zone_boundaries={"zone4": (163, 178), "zone2": (134, 149)},
        actual_rpe=7,
        actual_load_au=105,
        planned_load_au=100,
    )

    score_id = persist_session_score(repo, activity_id, result)

    row = repo.get_session_score(activity_id)
    assert row["id"] == score_id
    assert row["execution_score"] == pytest.approx(result["execution_score"])
    assert row["overpush_flag"] == result["overpush_flag"]
    assert row["underpush_flag"] == result["underpush_flag"]
    stored_breakdown = json.loads(row["score_breakdown_json"])
    assert stored_breakdown["hr_drift_score"] == 80.0
