---
status: accepted
---

# Deterministic core, LLM explains but never decides

Apex Coach could have let the local LLM (Ollama) reason directly over WHOOP/Strava data to produce training recommendations — the more common shape for an "AI coach." Instead, all decision logic (recovery/HRV/soreness classification, the Daily/Weekly/Monthly engines, zone and load calculations) is pure, deterministic Python with no LLM involvement, fully unit-testable via an exhaustive decision matrix. The LLM receives only the already-decided structured JSON output and turns it into natural-language rationale and conversational follow-up — it cannot alter or produce a `Decision Output`. This trades away whatever nuance an LLM might add to edge cases in exchange for auditability, explainability, and a test suite that can assert exact outputs for exact inputs, which matters because a wrong training recommendation has a physical injury cost.
