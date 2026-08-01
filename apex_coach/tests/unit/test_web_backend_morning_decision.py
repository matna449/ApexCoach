"""F17.2 (#84): POST /api/morning/decision against a fixture DB.

Ports the key scenarios from test_cli_morning.py to HTTP, since the
endpoint calls the identical shared functions (run_decision_pipeline /
persist_decision_with_explanation, extracted from cli/main.py in this same
ticket) — these are the same behaviors, just invoked over HTTP instead of
CliRunner.
"""

import importlib
import json
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from apex_coach.adapters.ollama_adapter import ExplanationResult
from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.plan_repository import PlanRepository
from apex_coach.db.schema import decisions, metadata
import sqlalchemy as sa


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


def _seed_whoop_data(engine, date_str, **overrides):
    repo = MetricsRepository(engine)
    fields = {
        "whoop_recovery_pct": 62.0,
        "whoop_hrv_ms": 71.4,
        "whoop_rhr_bpm": 48.0,
        "whoop_strain": 8.4,
        "whoop_sleep_hours": 7.5,
        **overrides,
    }
    repo.upsert_daily_metrics(date_str, **fields)


def _decisions_for(engine, date_str):
    with engine.begin() as conn:
        rows = conn.execute(
            sa.select(decisions).where(decisions.c.date == date_str).order_by(decisions.c.created_at)
        ).all()
    return [dict(r._mapping) for r in rows]


# HIIT's 3 fixed + 3 adaptive (left_knee_pain, right_knee_pain,
# shin_calf_tightness) answers, all low — no override.
HIIT_NO_OVERRIDE = {
    "fixed_answers": {"muscle_soreness": 3, "subjective_energy": 2, "sleep_quality_felt": 4},
    "adaptive_answers": {"left_knee_pain": 1, "right_knee_pain": 2, "shin_calf_tightness": 2},
}


def _mocked_ollama(explanation="Mock explanation."):
    """The endpoint always constructs RealOllamaAdapter (docs/adr/0023 —
    no mock toggle in the web UI), so every test must patch it; otherwise
    it hits an actual local Ollama instance, which is slow, non-
    deterministic, and absent in CI."""
    return patch("web.backend.main.RealOllamaAdapter")


def test_morning_decision_full_chain_persists_and_returns_explanation(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    _seed_whoop_data(engine, "2026-08-05")

    main_module, client = _client_for(db_path)
    with _mocked_ollama() as MockAdapterClass:
        MockAdapterClass.return_value.explain.return_value = ExplanationResult(
            explanation="Mock explanation.", degraded=False, banner=None, severity=None
        )
        response = client.post(
            "/api/morning/decision",
            json={"date": "2026-08-05", "session_type": "HIIT", **HIIT_NO_OVERRIDE},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recommendation"] in {"GO", "MODIFY", "MODALITY_SWAP", "ABORT"}
    assert body["explanation"] == "Mock explanation."
    assert body["override_triggered"] is False

    rows = _decisions_for(engine, "2026-08-05")
    assert len(rows) == 2
    assert rows[0]["llm_explanation"] is None  # bare, crash-safe row
    assert rows[1]["llm_explanation"] is not None  # fuller row, post-Ollama


def test_morning_decision_requires_whoop_data_persisted_first(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    # No _seed_whoop_data() call — nothing persisted for this date.

    _main_module, client = _client_for(db_path)
    response = client.post(
        "/api/morning/decision",
        json={"date": "2026-08-05", "session_type": "HIIT", **HIIT_NO_OVERRIDE},
    )

    assert response.status_code == 400
    assert "GET /api/morning/context" in response.json()["detail"]


def test_morning_decision_rejects_unknown_session_type(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    _seed_whoop_data(engine, "2026-08-05")

    _main_module, client = _client_for(db_path)
    response = client.post(
        "/api/morning/decision",
        json={"date": "2026-08-05", "session_type": "NotReal", **HIIT_NO_OVERRIDE},
    )

    assert response.status_code == 400


def test_morning_decision_override_triggers_abort(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    _seed_whoop_data(engine, "2026-08-05")

    # left_knee_pain=4 crosses the ABORT_STRENGTH_RUN/override threshold.
    override_answers = {
        "fixed_answers": {"muscle_soreness": 3, "subjective_energy": 2, "sleep_quality_felt": 4},
        "adaptive_answers": {"left_knee_pain": 4, "right_knee_pain": 2, "shin_calf_tightness": 2},
    }
    _main_module, client = _client_for(db_path)
    with _mocked_ollama() as MockAdapterClass:
        MockAdapterClass.return_value.explain.return_value = ExplanationResult(
            explanation="Mock explanation.", degraded=False, banner=None, severity=None
        )
        response = client.post(
            "/api/morning/decision",
            json={"date": "2026-08-05", "session_type": "HIIT", **override_answers},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recommendation"] == "ABORT"
    assert body["override_triggered"] is True
    assert any("left_knee_pain" in r for r in body["override_reasons"])


def test_morning_decision_degraded_ollama_returns_banner_and_skips_second_row(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    _seed_whoop_data(engine, "2026-08-05")

    main_module, client = _client_for(db_path)
    degraded = ExplanationResult(
        explanation=None,
        degraded=True,
        banner="[Ollama offline -- start with: ollama serve]",
        severity="WARN",
    )
    with patch("web.backend.main.RealOllamaAdapter") as MockAdapterClass:
        MockAdapterClass.return_value.explain.return_value = degraded
        response = client.post(
            "/api/morning/decision",
            json={"date": "2026-08-05", "session_type": "HIIT", **HIIT_NO_OVERRIDE},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["explanation"] is None
    assert body["banner"] == degraded.banner
    assert body["severity"] == "WARN"

    rows = _decisions_for(engine, "2026-08-05")
    assert len(rows) == 1  # only the pre-Ollama row — decision itself wasn't lost


def test_morning_decision_context_matches_api_contract_shape(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    _seed_whoop_data(engine, "2026-08-05")
    PlanRepository(engine).insert_monthly_target(
        month_start_date="2026-08-01",
        periodisation_phase="BUILD",
        load_target_total=500.0,
        race_date="2026-10-01",
    )

    _main_module, client = _client_for(db_path)
    with _mocked_ollama() as MockAdapterClass:
        MockAdapterClass.return_value.explain.return_value = ExplanationResult(
            explanation="Mock explanation.", degraded=False, banner=None, severity=None
        )
        response = client.post(
            "/api/morning/decision",
            json={"date": "2026-08-05", "session_type": "HIIT", **HIIT_NO_OVERRIDE},
        )

    assert response.status_code == 200, response.text
    ctx = response.json()["decision_context"]
    assert set(ctx.keys()) == {
        "date",
        "athlete_context",
        "todays_plan",
        "biometrics",
        "morning_check",
        "decision",
        "weekly_context",
    }
    assert ctx["date"] == "2026-08-05"
    assert ctx["todays_plan"]["scheduled_session"] == "HIIT"
    assert ctx["morning_check"]["adaptive_checks"] == HIIT_NO_OVERRIDE["adaptive_answers"]
