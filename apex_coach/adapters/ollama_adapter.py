"""Ollama explanation adapter — Protocol + MockOllamaAdapter/RealOllamaAdapter
(ADR-0010, ADR-0020).

RealOllamaAdapter (F09.2) raises these same errors from real httpx calls
against a local Ollama instance; MockOllamaAdapter raises them internally
too, so its explain() rehearses the exact catch-and-degrade shape the real
one needs.
"""

import json
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from apex_coach.adapters.errors import (
    AdapterMalformedResponseError,
    AdapterTimeoutError,
    AdapterUnavailableError,
)

FailureMode = Literal[
    "connection_refused", "model_not_found", "timeout", "malformed_output"
]

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1:8b"
OLLAMA_TIMEOUT_S = 30

SYSTEM_PROMPT = (
    "You are Apex Coach, a sports science assistant for an endurance athlete "
    "following a pyramidal training model. You receive structured JSON with "
    "biometric data, the training plan, and the decision made by the coaching "
    "engine. Explain the decision in 3-5 sentences. Cite the specific metrics "
    "that drove it. Do not add anything the engine has not already decided. "
    "Speak directly to the athlete."
)


class OllamaModelNotFoundError(AdapterUnavailableError):
    pass


@dataclass(frozen=True)
class ExplanationResult:
    explanation: str | None
    degraded: bool
    banner: str | None
    severity: Literal["WARN", "INFO"] | None


class OllamaAdapterProtocol(Protocol):
    def explain(self, decision_context: dict) -> ExplanationResult: ...
    def ask_followup(
        self, decision_context: dict, prior_explanation: str, question: str
    ) -> ExplanationResult: ...


class MockOllamaAdapter:
    """Deterministic simulation of the 4 documented failure modes (API Contract §6.3)."""

    def __init__(
        self,
        fail_mode: FailureMode | None = None,
        malformed_text: str = "",
    ):
        self._fail_mode = fail_mode
        self._malformed_text = malformed_text

    def _call_model(self, prompt_content: str) -> str:
        if self._fail_mode == "connection_refused":
            raise AdapterUnavailableError("connection refused")
        if self._fail_mode == "model_not_found":
            raise OllamaModelNotFoundError("model not pulled")
        if self._fail_mode == "timeout":
            raise AdapterTimeoutError("request exceeded 30s")
        if self._fail_mode == "malformed_output":
            raise AdapterMalformedResponseError(self._malformed_text)

        return f"Mock explanation for: {prompt_content[:40]}"

    def explain(self, decision_context: dict) -> ExplanationResult:
        recommendation = decision_context.get("decision", {}).get(
            "recommendation", "UNKNOWN"
        )
        return _degrade_on_failure(
            lambda: self._call_model(f"decision {recommendation}")
        )

    def ask_followup(
        self, decision_context: dict, prior_explanation: str, question: str
    ) -> ExplanationResult:
        return _degrade_on_failure(
            lambda: self._call_model(f"followup: {question}")
        )


def _degrade_on_failure(call_model) -> ExplanationResult:
    """Shared explain()/ask_followup() shape (§6.3): attempt the call,
    classify what went wrong, degrade gracefully — never crash or go
    silent. Both MockOllamaAdapter and RealOllamaAdapter route through
    this so the two stay behaviourally identical."""
    try:
        explanation = call_model()
    except OllamaModelNotFoundError:
        return ExplanationResult(
            explanation=None,
            degraded=True,
            banner="[Run: ollama pull llama3.1:8b to enable explanations]",
            severity="WARN",
        )
    except AdapterUnavailableError:
        return ExplanationResult(
            explanation=None,
            degraded=True,
            banner="[Ollama offline -- start with: ollama serve]",
            severity="WARN",
        )
    except AdapterTimeoutError:
        return ExplanationResult(
            explanation=None,
            degraded=True,
            banner=None,
            severity="WARN",
        )
    except AdapterMalformedResponseError as e:
        # Graceful degradation: output the raw model text as-is rather
        # than crashing on a parsing failure (§6.3, malformed output row).
        return ExplanationResult(
            explanation=str(e),
            degraded=True,
            banner=None,
            severity="INFO",
        )

    return ExplanationResult(
        explanation=explanation,
        degraded=False,
        banner=None,
        severity=None,
    )


class RealOllamaAdapter:
    """Drop-in replacement for MockOllamaAdapter behind OllamaAdapterProtocol.
    Wraps the local Ollama POST /api/chat call (API Contract §4.2), handles
    §6.3's failure modes. See docs/adr/0020."""

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = OLLAMA_MODEL,
        http_client: httpx.Client | None = None,
    ):
        self._model = model
        self._client = http_client or httpx.Client(base_url=base_url, timeout=OLLAMA_TIMEOUT_S)

    def _chat(self, messages: list[dict]) -> str:
        try:
            response = self._client.post(
                "/api/chat",
                json={
                    "model": self._model,
                    "stream": False,
                    "options": {"temperature": 0.3, "top_p": 0.9},
                    "messages": messages,
                },
            )
        except httpx.TimeoutException as e:
            raise AdapterTimeoutError(f"Ollama request exceeded {OLLAMA_TIMEOUT_S}s") from e
        except httpx.ConnectError as e:
            raise AdapterUnavailableError(
                "connection refused — is `ollama serve` running?"
            ) from e

        if response.status_code == 404:
            raise OllamaModelNotFoundError(f"model not pulled: {self._model}")
        response.raise_for_status()

        try:
            payload = response.json()
            return payload["message"]["content"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise AdapterMalformedResponseError(str(e)) from e

    def explain(self, decision_context: dict) -> ExplanationResult:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(decision_context)},
        ]
        return _degrade_on_failure(lambda: self._chat(messages))

    def ask_followup(
        self, decision_context: dict, prior_explanation: str, question: str
    ) -> ExplanationResult:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(decision_context)},
            {"role": "assistant", "content": prior_explanation},
            {"role": "user", "content": question},
        ]
        return _degrade_on_failure(lambda: self._chat(messages))
