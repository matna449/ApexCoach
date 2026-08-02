"""F19.4 (#119): GET /api/plan/week against a fixture DB.

Mirrors test_web_backend_morning_decision.py's structure (fixture-DB engine
+ reloaded app module + TestClient). The endpoint only *reads*
weekly_plans.generated_structure_json — the same JSON F19.2's
`generate-week-structure` CLI command already persists — so these tests seed
that column directly rather than re-running the generator.
"""

import importlib
import json
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from apex_coach.db.engine import create_engine
from apex_coach.db.plan_repository import PlanRepository
from apex_coach.db.schema import metadata


def _env(db_path):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": "test",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "WHOOP_CLIENT_ID": "test-client-id",
        "WHOOP_CLIENT_SECRET": "test-client-secret",
    }


def _client_for(db_path):
    with patch.dict(os.environ, _env(db_path), clear=True):
        import web.backend.main as main_module

        importlib.reload(main_module)
    return main_module, TestClient(main_module.app)


GENERATED_STRUCTURE = [
    {
        "day": "Monday",
        "session_type": "HIIT",
        "structure": {
            "type": "intervals",
            "rep_count": 6,
            "work_zone": "zone5",
            "work_hr_bpm": 172,
            "work_min": 3.0,
            "recovery_zone": "zone2",
            "recovery_hr_bpm": 140,
            "recovery_min": 2.0,
            "warmup_cooldown_min": 10.0,
            "total_duration_min": 40.0,
        },
    },
    {
        "day": "Tuesday",
        "session_type": "Zone2_Long",
        "structure": {
            "type": "single_block",
            "zone": "zone2",
            "target_hr_bpm": 140,
            "main_set_min": 60.0,
            "warmup_cooldown_min": 10.0,
            "total_duration_min": 70.0,
        },
    },
    {
        "day": "Wednesday",
        "session_type": "Rest",
        "structure": {"type": "rest", "duration_min": 0.0},
    },
]


def test_plan_week_returns_generated_structure_with_every_session_not_pushed(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    plan_repo = PlanRepository(engine)
    plan_repo.insert_weekly_plan(
        week_start_date="2026-08-03",
        planned_sessions_json=json.dumps(
            [{"day": e["day"], "session_type": e["session_type"]} for e in GENERATED_STRUCTURE]
        ),
        generated_structure_json=json.dumps(GENERATED_STRUCTURE),
        # Seeded to prove the endpoint deliberately ignores this column for
        # now (#119: "every session shows as not pushed" until F19.7/#123).
        pushed_event_ids_json=json.dumps({"Monday": "12345"}),
    )

    _main_module, client = _client_for(db_path)
    response = client.get("/api/plan/week", params={"week_start": "2026-08-03"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["week_start_date"] == "2026-08-03"
    assert body["generated"] is True
    assert len(body["days"]) == 3

    monday = body["days"][0]
    assert monday["day"] == "Monday"
    assert monday["session_type"] == "HIIT"
    assert monday["structure"] == GENERATED_STRUCTURE[0]["structure"]
    assert monday["pushed"] is False  # not True, despite the seeded event id above

    assert all(day["pushed"] is False for day in body["days"])


def test_plan_week_not_yet_generated_returns_empty_days(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    plan_repo = PlanRepository(engine)
    plan_repo.insert_weekly_plan(
        week_start_date="2026-08-03",
        planned_sessions_json=json.dumps(
            [{"day": "Monday", "session_type": "HIIT"}]
        ),
        # No generated_structure_json — F19.2's generation hasn't run yet.
    )

    _main_module, client = _client_for(db_path)
    response = client.get("/api/plan/week", params={"week_start": "2026-08-03"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"week_start_date": "2026-08-03", "generated": False, "days": []}


def test_plan_week_no_weekly_plan_row_returns_404(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    _main_module, client = _client_for(db_path)
    response = client.get("/api/plan/week", params={"week_start": "2026-08-03"})

    assert response.status_code == 404
    assert "2026-08-03" in response.json()["detail"]


def test_plan_week_rejects_invalid_date(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    _main_module, client = _client_for(db_path)
    response = client.get("/api/plan/week", params={"week_start": "not-a-date"})

    assert response.status_code == 400
