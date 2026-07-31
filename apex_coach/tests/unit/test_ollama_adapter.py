from apex_coach.adapters.ollama_adapter import MockOllamaAdapter

DECISION_CONTEXT = {
    "date": "2026-07-30",
    "decision": {"recommendation": "MODIFY", "rationale": {}},
}


def test_happy_path_returns_explanation_not_degraded():
    adapter = MockOllamaAdapter()

    result = adapter.explain(DECISION_CONTEXT)

    assert result.explanation is not None
    assert "MODIFY" in result.explanation
    assert result.degraded is False
    assert result.banner is None
    assert result.severity is None


def test_connection_refused_degrades_with_warn_banner():
    adapter = MockOllamaAdapter(fail_mode="connection_refused")

    result = adapter.explain(DECISION_CONTEXT)

    assert result.explanation is None
    assert result.degraded is True
    assert result.banner == "[Ollama offline -- start with: ollama serve]"
    assert result.severity == "WARN"


def test_model_not_found_degrades_with_warn_banner():
    adapter = MockOllamaAdapter(fail_mode="model_not_found")

    result = adapter.explain(DECISION_CONTEXT)

    assert result.explanation is None
    assert result.degraded is True
    assert result.banner == "[Run: ollama pull gemma4:latest to enable explanations]"
    assert result.severity == "WARN"


def test_timeout_degrades_with_warn_and_no_banner():
    adapter = MockOllamaAdapter(fail_mode="timeout")

    result = adapter.explain(DECISION_CONTEXT)

    assert result.explanation is None
    assert result.degraded is True
    assert result.banner is None
    assert result.severity == "WARN"


def test_malformed_output_returns_raw_text_with_info_severity():
    adapter = MockOllamaAdapter(
        fail_mode="malformed_output", malformed_text="raw unparseable model text"
    )

    result = adapter.explain(DECISION_CONTEXT)

    assert result.explanation == "raw unparseable model text"
    assert result.degraded is True
    assert result.banner is None
    assert result.severity == "INFO"


def test_no_failure_mode_never_raises_regardless_of_input():
    adapter = MockOllamaAdapter()

    result = adapter.explain({})

    assert result.explanation is not None
    assert result.degraded is False
