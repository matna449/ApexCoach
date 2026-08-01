"""F17.3 (#85): POST /api/morning/followup.

The endpoint always constructs RealOllamaAdapter (no mock toggle,
ADR-0023), so every test here mocks it explicitly — an unmocked test
would hit a real local Ollama instance: slow, non-deterministic, and
absent in CI (a mistake caught and fixed in #84's own tests before they
were pushed).
"""

import importlib
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from apex_coach.adapters.ollama_adapter import ExplanationResult
from apex_coach.db.engine import create_engine
from apex_coach.db.schema import metadata


def _env(db_path):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": "test",
        "DATABASE_URL": f"sqlite:///{db_path}",
    }


def _client_for(db_path):
    with patch.dict(os.environ, _env(db_path), clear=True):
        import web.backend.main as main_module

        importlib.reload(main_module)
    return TestClient(main_module.app)


# A hand-built decision_context payload, not chained through an actual
# prior /decision call — per the ticket, keeps this test focused on the
# follow-up endpoint's own request/response shape.
SAMPLE_CONTEXT = {
    "date": "2026-08-05",
    "athlete_context": {"training_phase": None, "race_date": None, "weeks_to_race": None},
    "todays_plan": {"scheduled_session": "HIIT", "session_description": "..."},
    "biometrics": {},
    "morning_check": {},
    "decision": {"recommendation": "GO", "rationale": {}},
    "weekly_context": {},
}


def test_morning_followup_happy_path_returns_explanation(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    client = _client_for(db_path)
    with patch("web.backend.main.RealOllamaAdapter") as MockAdapterClass:
        MockAdapterClass.return_value.ask_followup.return_value = ExplanationResult(
            explanation="Because your HRV is suppressed.", degraded=False, banner=None, severity=None
        )
        response = client.post(
            "/api/morning/followup",
            json={
                "decision_context": SAMPLE_CONTEXT,
                "prior_explanation": "You're cleared to go.",
                "question": "why?",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["explanation"] == "Because your HRV is suppressed."
    assert body["banner"] is None
    assert body["severity"] is None

    MockAdapterClass.return_value.ask_followup.assert_called_once_with(
        SAMPLE_CONTEXT, "You're cleared to go.", "why?"
    )


def test_morning_followup_degrades_gracefully_with_banner(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    client = _client_for(db_path)
    with patch("web.backend.main.RealOllamaAdapter") as MockAdapterClass:
        MockAdapterClass.return_value.ask_followup.return_value = ExplanationResult(
            explanation=None,
            degraded=True,
            banner="[Ollama offline -- start with: ollama serve]",
            severity="WARN",
        )
        response = client.post(
            "/api/morning/followup",
            json={
                "decision_context": SAMPLE_CONTEXT,
                "prior_explanation": "You're cleared to go.",
                "question": "what if I do it anyway?",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["explanation"] is None
    assert body["banner"] == "[Ollama offline -- start with: ollama serve]"
    assert body["severity"] == "WARN"
