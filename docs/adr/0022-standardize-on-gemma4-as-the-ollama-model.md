---
status: accepted
---

# Standardize on gemma4:latest as the Ollama model, superseding llama3.1:8b

ADR-0020 used `gemma4:latest` as a live-verification stand-in for `llama3.1:8b`, framed as temporary because llama3.1:8b wasn't pulled on the development machine yet. The athlete has since decided to stay on `gemma4:latest` permanently rather than pull llama3.1:8b — it's already local (9.6 GB, comfortably inside the 24 GB M4 Pro's headroom), and nothing in the explanation layer depends on a specific model: `RealOllamaAdapter` talks to Ollama's standard `POST /api/chat` endpoint, which is model-agnostic, and `SYSTEM_PROMPT` doesn't reference the model by name.

**`OLLAMA_MODEL` in `apex_coach/adapters/ollama_adapter.py` is updated to `"gemma4:latest"`, hardcoded exactly as `OLLAMA_BASE_URL`/`OLLAMA_TIMEOUT_S` already are** — no env-var indirection was introduced. Nothing else in this codebase reads Ollama config from `.env` today (despite the SDD's example `.env` block listing `OLLAMA_MODEL`/`OLLAMA_BASE_URL` as if it were wired up — it isn't, and this ADR doesn't change that), so making only the model configurable would be inconsistent with the base URL and timeout staying fixed constants. If Ollama config ever needs to be runtime-configurable, both should move to `settings.py` together, not just the model.

**The model-not-found banner text now interpolates `OLLAMA_MODEL`** (`f"[Run: ollama pull {OLLAMA_MODEL} to enable explanations]"`) instead of hardcoding `llama3.1:8b` — a latent bug this switch surfaced: the instruction to the athlete must name whichever model is actually configured, not whichever model happened to be current when that string was first written.

Documentation updated to match: README, PRD, SDD, and API Integration Contract §4.1's model/hardware-fit line all referred to LLaMA 3.1 8B as the chosen model; those are corrected to `gemma4:latest` so a future ticket reading the contract doesn't build against a stale model name. ADR-0020's own text is left as-is — it accurately describes what was true at the time (gemma4 as a stand-in) — and this ADR is the record of the follow-up decision to keep it.
