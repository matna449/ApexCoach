"""Ollama explanation adapter — Protocol + MockOllamaAdapter (ADR-0010).

RealOllamaAdapter (F09.2) will raise these same errors from real httpx/
ollama-python calls; MockOllamaAdapter raises them internally too, so its
explain() rehearses the exact catch-and-degrade shape the real one needs.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from apex_coach.adapters.errors import (
    AdapterMalformedResponseError,
    AdapterTimeoutError,
    AdapterUnavailableError,
)

FailureMode = Literal[
    "connection_refused", "model_not_found", "timeout", "malformed_output"
]


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


class MockOllamaAdapter:
    """Deterministic simulation of the 4 documented failure modes (API Contract §6.3)."""

    def __init__(
        self,
        fail_mode: FailureMode | None = None,
        malformed_text: str = "",
    ):
        self._fail_mode = fail_mode
        self._malformed_text = malformed_text

    def _call_model(self, decision_context: dict) -> str:
        if self._fail_mode == "connection_refused":
            raise AdapterUnavailableError("connection refused")
        if self._fail_mode == "model_not_found":
            raise OllamaModelNotFoundError("model not pulled")
        if self._fail_mode == "timeout":
            raise AdapterTimeoutError("request exceeded 30s")
        if self._fail_mode == "malformed_output":
            raise AdapterMalformedResponseError(self._malformed_text)

        recommendation = decision_context.get("decision", {}).get(
            "recommendation", "UNKNOWN"
        )
        return f"Mock explanation for decision: {recommendation}"

    def explain(self, decision_context: dict) -> ExplanationResult:
        try:
            explanation = self._call_model(decision_context)
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
