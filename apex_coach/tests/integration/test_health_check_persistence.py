import json

import pytest

from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.schema import metadata
from apex_coach.services.health_check import evaluate_health_check, persist_health_check


@pytest.fixture
def repo():
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    return MetricsRepository(engine)


def test_persist_inserts_when_no_row_exists_yet(repo):
    result = evaluate_health_check(
        "Recovery",
        {"muscle_soreness": 2, "subjective_energy": 4, "sleep_quality_felt": 4},
        {"general_wellbeing": 4},
    )

    persist_health_check(repo, "2026-07-30", result)

    row = repo.get_daily_metrics("2026-07-30")
    assert row["muscle_soreness"] == 2
    assert row["subjective_energy"] == 4
    assert row["sleep_quality_felt"] == 4
    stored = json.loads(row["health_check_json"])
    assert stored["session_type"] == "Recovery"


def test_persist_updates_existing_row_from_whoop_fetch_without_touching_it(repo):
    # Simulates WHOOP fetch (a separate writer) running first.
    repo.insert_daily_metrics(date="2026-07-30", whoop_recovery_pct=62.0, whoop_hrv_ms=71.4)

    result = evaluate_health_check(
        "Rest",
        {"muscle_soreness": 3, "subjective_energy": 3, "sleep_quality_felt": 3},
        {"general_wellbeing": 4},
    )
    persist_health_check(repo, "2026-07-30", result)

    row = repo.get_daily_metrics("2026-07-30")
    assert row["whoop_recovery_pct"] == 62.0
    assert row["whoop_hrv_ms"] == 71.4
    assert row["muscle_soreness"] == 3


def test_persist_health_check_running_first_then_whoop_update_both_succeed(repo):
    result = evaluate_health_check(
        "Rest",
        {"muscle_soreness": 3, "subjective_energy": 3, "sleep_quality_felt": 3},
        {"general_wellbeing": 4},
    )
    persist_health_check(repo, "2026-07-30", result)

    # Simulates WHOOP fetch running second, updating the same row.
    repo.upsert_daily_metrics("2026-07-30", whoop_recovery_pct=62.0)

    row = repo.get_daily_metrics("2026-07-30")
    assert row["muscle_soreness"] == 3
    assert row["whoop_recovery_pct"] == 62.0
