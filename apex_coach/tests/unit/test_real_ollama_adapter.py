import json

import httpx
import pytest

from apex_coach.adapters.ollama_adapter import RealOllamaAdapter

DECISION_CONTEXT = {
    "date": "2026-07-30",
    "decision": {"recommendation": "MODIFY", "rationale": {"recovery_zone": "YELLOW (62%)"}},
}


def _adapter(http_client=None) -> RealOllamaAdapter:
    return RealOllamaAdapter(http_client=http_client)


def test_explain_happy_path(httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:11434/api/chat",
        json={"message": {"role": "assistant", "content": "You're at 62% recovery..."}},
    )

    result = _adapter().explain(DECISION_CONTEXT)

    assert result.explanation == "You're at 62% recovery..."
    assert result.degraded is False
    assert result.banner is None
    assert result.severity is None


def test_explain_sends_decision_context_as_user_message(httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:11434/api/chat",
        json={"message": {"content": "ok"}},
    )

    _adapter().explain(DECISION_CONTEXT)

    request = httpx_mock.get_requests()[0]
    payload = json.loads(request.read())
    assert payload["model"] == "llama3.1:8b"
    assert payload["stream"] is False
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["role"] == "user"
    assert "MODIFY" in payload["messages"][1]["content"]


def test_ask_followup_includes_prior_explanation_and_question(httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:11434/api/chat",
        json={"message": {"content": "Because your HRV is suppressed."}},
    )

    result = _adapter().ask_followup(DECISION_CONTEXT, "prior explanation text", "why?")

    assert result.explanation == "Because your HRV is suppressed."
    request = httpx_mock.get_requests()[0]
    payload = json.loads(request.read())
    roles = [m["role"] for m in payload["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert payload["messages"][2]["content"] == "prior explanation text"
    assert payload["messages"][3]["content"] == "why?"


def test_connection_refused_degrades_with_warn_banner(httpx_mock):
    httpx_mock.add_exception(
        httpx.ConnectError("connection refused"), url="http://localhost:11434/api/chat"
    )

    result = _adapter().explain(DECISION_CONTEXT)

    assert result.explanation is None
    assert result.degraded is True
    assert result.banner == "[Ollama offline -- start with: ollama serve]"
    assert result.severity == "WARN"


def test_timeout_degrades_with_warn_and_no_banner(httpx_mock):
    httpx_mock.add_exception(
        httpx.TimeoutException("timed out"), url="http://localhost:11434/api/chat"
    )

    result = _adapter().explain(DECISION_CONTEXT)

    assert result.explanation is None
    assert result.degraded is True
    assert result.banner is None
    assert result.severity == "WARN"


def test_model_not_found_degrades_with_warn_banner(httpx_mock):
    httpx_mock.add_response(url="http://localhost:11434/api/chat", status_code=404)

    result = _adapter().explain(DECISION_CONTEXT)

    assert result.explanation is None
    assert result.degraded is True
    assert result.banner == "[Run: ollama pull llama3.1:8b to enable explanations]"
    assert result.severity == "WARN"


def test_malformed_json_returns_raw_text_with_info_severity(httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:11434/api/chat",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )

    result = _adapter().explain(DECISION_CONTEXT)

    assert result.explanation is not None
    assert result.degraded is True
    assert result.banner is None
    assert result.severity == "INFO"


def test_response_missing_message_key_returns_raw_text_with_info_severity(httpx_mock):
    httpx_mock.add_response(url="http://localhost:11434/api/chat", json={"unexpected": "shape"})

    result = _adapter().explain(DECISION_CONTEXT)

    assert result.explanation is not None
    assert result.degraded is True
    assert result.severity == "INFO"


@pytest.mark.live_llm
def test_live_explain_then_followup_produces_coherent_answers():
    """SDD §7.2: the one live-call integration test — run manually with
    --run-live-llm against a real `ollama serve` + `ollama pull llama3.1:8b`.
    Not relied on for failure-mode coverage (that's the httpx_mock tests
    above and MockOllamaAdapter's, F09.1)."""
    adapter = RealOllamaAdapter()

    result = adapter.explain(DECISION_CONTEXT)
    assert result.degraded is False
    assert result.explanation
    assert len(result.explanation) > 20

    followup = adapter.ask_followup(DECISION_CONTEXT, result.explanation, "why?")
    assert followup.degraded is False
    assert followup.explanation
    assert len(followup.explanation) > 10
