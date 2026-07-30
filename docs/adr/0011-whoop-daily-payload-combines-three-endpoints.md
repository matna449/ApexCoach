---
status: accepted
---

# WhoopDailyPayload combines all 3 WHOOP endpoints; whoop_adapter exposes one public method

SDD's Module Contract table named `WhoopDailyPayload` as `whoop_adapter`'s output type, but no such model was ever defined — API Contract §2.2-§2.4 only specified per-endpoint models (`WhoopRecovery`) and per-endpoint "Adapter Method" declarations (`get_latest_recovery()`, `get_latest_cycle()`), with §2.4 (sleep) missing even that. Building F01.1 surfaced that `daily_metrics` needs fields sourced from all three endpoints — recovery gives `whoop_recovery_pct`/`whoop_hrv_ms`/`whoop_rhr_bpm`, cycle gives `whoop_strain`, sleep gives `whoop_sleep_hours` — so a `WhoopDailyPayload` that only wrapped one endpoint's data couldn't actually back that table.

We're defining `WhoopDailyPayload` (API Contract §2.5) as a composite of `WhoopRecovery`, `WhoopCycle`, and a new `WhoopSleep` model (the latter two not previously specified), with convenience properties (`recovery_pct`, `hrv_ms`, `rhr_bpm`, `strain`, `sleep_hours`) that flatten the nested structure to match `daily_metrics`' column names directly. `whoop_adapter` exposes exactly one public method, `get_daily_payload() -> WhoopDailyPayload`, that internally calls all three WHOOP endpoints (Real) or returns all three mock payloads (Mock) and assembles the composite. The per-endpoint methods named in §2.2/§2.3 (`get_latest_recovery`, `get_latest_cycle`) become internal implementation detail, not part of the adapter's public surface — corrected in place in the API Contract.

Alternative considered: three separate public methods on `whoop_adapter`, one per endpoint, matching §2.2/§2.3's literal "Adapter Method" declarations, with the caller (Orchestrator) responsible for calling all three and assembling `WhoopDailyPayload` itself. Rejected because it pushes an assembly responsibility onto every caller for data that's always needed together in this system — there's no documented scenario where the Orchestrator wants recovery without cycle and sleep for the same day — and it leaves `WhoopDailyPayload` without a single owner responsible for producing it.
