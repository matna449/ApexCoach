"""F17.1 (#83): GET /api/morning/context against a fixture DB.

Follows the pattern established in test_web_backend_hrv_trend.py: reload
web.backend.main under a tmp_path DATABASE_URL before each test, patch
RealWhoopAdapter the same way test_cli_morning.py patches it for the CLI's
own `morning` command.
"""

import importlib
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from apex_coach.adapters.whoop_adapter import MockWhoopAdapter
from apex_coach.db.engine import create_engine
from apex_coach.db.plan_repository import PlanRepository
from apex_coach.db.schema import metadata


def _env(db_path, **extra):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": "test",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "WHOOP_CLIENT_ID": "test-client-id",
        "WHOOP_CLIENT_SECRET": "test-client-secret",
        **extra,
    }


def _client_for(db_path, **extra_env):
    with patch.dict(os.environ, _env(db_path, **extra_env), clear=True):
        import web.backend.main as main_module

        importlib.reload(main_module)
    return TestClient(main_module.app)


def _seed_week(db_path, **days):
    engine = create_engine(str(db_path))
    plan_repo = PlanRepository(engine)
    all_days = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
    for day in all_days - days.keys():
        days[day] = "Rest"
    import json

    plan_repo.insert_weekly_plan(
        week_start_date=days.pop("week_start"),
        planned_sessions_json=json.dumps(
            [{"day": day.capitalize(), "session_type": st} for day, st in days.items()]
        ),
    )


def test_morning_context_resolves_session_from_plan_and_returns_questions(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    _seed_week(db_path, week_start="2026-08-03", monday="HIIT")

    payload = MockWhoopAdapter().get_daily_payload("2026-08-03")
    client = _client_for(db_path)
    with patch("web.backend.main.RealWhoopAdapter") as MockAdapterClass:
        MockAdapterClass.return_value.get_daily_payload.return_value = payload
        response = client.get("/api/morning/context?date=2026-08-03")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["date"] == "2026-08-03"
    assert body["session_type"] == "HIIT"
    assert body["biometrics"]["whoop_hrv_ms"] == payload.whoop_hrv_ms
    fixed_keys = {q["key"] for q in body["questions"]["fixed"]}
    assert fixed_keys == {"muscle_soreness", "subjective_energy", "sleep_quality_felt"}
    adaptive_keys = {q["key"] for q in body["questions"]["adaptive"]}
    assert adaptive_keys == {"left_knee_pain", "right_knee_pain", "shin_calf_tightness"}

    from apex_coach.db.metrics_repository import MetricsRepository

    row = MetricsRepository(engine).get_daily_metrics("2026-08-03")
    assert row["whoop_hrv_ms"] == payload.whoop_hrv_ms


def test_morning_context_falls_back_to_session_type_param_when_no_plan(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    payload = MockWhoopAdapter().get_daily_payload("2026-08-05")
    client = _client_for(db_path)
    with patch("web.backend.main.RealWhoopAdapter") as MockAdapterClass:
        MockAdapterClass.return_value.get_daily_payload.return_value = payload
        response = client.get(
            "/api/morning/context?date=2026-08-05&session_type=Zone2_Short"
        )

    assert response.status_code == 200, response.text
    assert response.json()["session_type"] == "Zone2_Short"


def test_morning_context_no_plan_no_fallback_returns_409_with_biometrics(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    payload = MockWhoopAdapter().get_daily_payload("2026-08-05")
    client = _client_for(db_path)
    with patch("web.backend.main.RealWhoopAdapter") as MockAdapterClass:
        MockAdapterClass.return_value.get_daily_payload.return_value = payload
        response = client.get("/api/morning/context?date=2026-08-05")

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "no_plan_for_date"
    assert detail["biometrics"]["whoop_hrv_ms"] == payload.whoop_hrv_ms
    assert "HIIT" in detail["available_session_types"]


def test_morning_context_requires_whoop_credentials(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    client = _client_for(db_path, WHOOP_CLIENT_ID="", WHOOP_CLIENT_SECRET="")
    response = client.get("/api/morning/context?date=2026-08-05&session_type=HIIT")

    assert response.status_code == 400
    assert "WHOOP_CLIENT_ID" in response.json()["detail"]


def test_morning_context_rejects_unknown_session_type(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    client = _client_for(db_path)
    response = client.get("/api/morning/context?date=2026-08-05&session_type=NotReal")

    assert response.status_code == 400


def test_morning_context_rejects_invalid_date(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    client = _client_for(db_path)
    response = client.get("/api/morning/context?date=not-a-date")

    assert response.status_code == 400


# -- #132: existing_decision rehydration ------------------------------------


def test_morning_context_omits_existing_decision_when_none_persisted(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    _seed_week(db_path, week_start="2026-08-03", monday="HIIT")

    payload = MockWhoopAdapter().get_daily_payload("2026-08-03")
    client = _client_for(db_path)
    with patch("web.backend.main.RealWhoopAdapter") as MockAdapterClass:
        MockAdapterClass.return_value.get_daily_payload.return_value = payload
        response = client.get("/api/morning/context?date=2026-08-03")

    assert response.status_code == 200, response.text
    assert "existing_decision" not in response.json()


def test_morning_context_omits_existing_decision_for_bare_crash_safe_row_only(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    _seed_week(db_path, week_start="2026-08-03", monday="HIIT")

    plan_repo = PlanRepository(engine)
    from apex_coach.db.metrics_repository import MetricsRepository

    MetricsRepository(engine).insert_daily_metrics(date="2026-08-03")
    # The bare pre-Ollama row (ADR-0001): no llm_explanation, no
    # decision_context_json.
    plan_repo.insert_decision(date="2026-08-03", recommendation="GO")

    payload = MockWhoopAdapter().get_daily_payload("2026-08-03")
    client = _client_for(db_path)
    with patch("web.backend.main.RealWhoopAdapter") as MockAdapterClass:
        MockAdapterClass.return_value.get_daily_payload.return_value = payload
        response = client.get("/api/morning/context?date=2026-08-03")

    assert response.status_code == 200, response.text
    assert "existing_decision" not in response.json()


def test_morning_context_returns_existing_decision_when_full_decision_persisted(tmp_path):
    import json

    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    _seed_week(db_path, week_start="2026-08-03", monday="HIIT")

    plan_repo = PlanRepository(engine)
    from apex_coach.db.metrics_repository import MetricsRepository

    MetricsRepository(engine).insert_daily_metrics(date="2026-08-03")
    decision_context = {
        "date": "2026-08-03",
        "decision": {
            "rationale": {
                "rule_applied": "Recovery and HRV both look solid this morning.",
                "rationale": "Recovery and HRV both look solid this morning.",
                "override_triggered": False,
                "override_reasons": [],
                "check_recovery_week_trigger": False,
            }
        },
    }
    plan_repo.insert_decision(
        date="2026-08-03",
        recommendation="GO",
        rationale_json=json.dumps(decision_context["decision"]["rationale"]),
        llm_explanation="You're well recovered -- proceed as planned.",
        decision_context_json=json.dumps(decision_context),
    )

    payload = MockWhoopAdapter().get_daily_payload("2026-08-03")
    client = _client_for(db_path)
    with patch("web.backend.main.RealWhoopAdapter") as MockAdapterClass:
        MockAdapterClass.return_value.get_daily_payload.return_value = payload
        response = client.get("/api/morning/context?date=2026-08-03")

    assert response.status_code == 200, response.text
    existing = response.json()["existing_decision"]
    assert existing["recommendation"] == "GO"
    assert existing["rationale"] == "Recovery and HRV both look solid this morning."
    assert existing["explanation"] == "You're well recovered -- proceed as planned."
    assert existing["override_triggered"] is False
    assert existing["override_reasons"] == []
    assert existing["check_recovery_week_trigger"] is False
    assert existing["banner"] is None
    assert existing["severity"] is None
    assert existing["decision_context"] == decision_context
