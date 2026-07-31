---
status: accepted
---

# RealWhoopAdapter: local callback server, all 3 endpoints, retries live in the adapter, stale-data fallback deferred to the caller

Building F01.2 required turning API Contract §2.1's OAuth flow and §6.1's failure table into working code, not just documented behavior.

**A temporary local HTTP server captures the OAuth callback.** WHOOP's redirect (`http://localhost:8080/callback`) needs something listening to receive the authorization code. We're spinning one up for the duration of the one-time handshake (`adapters/oauth_pkce.py`'s `wait_for_callback()`) rather than asking the athlete to copy the code out of a broken page's URL bar — the same pattern `gh auth login`/`gcloud auth login` use. It shuts down automatically once the callback arrives or times out. This module is provider-agnostic (PKCE generation, state, callback capture) since Strava's OAuth flow (F02.2) will need the identical mechanism.

**RealWhoopAdapter implements all 3 endpoints, not just `/v1/recovery`.** The ticket's "What to build" names only §2.2 (`GET /v1/recovery`), but its own acceptance criterion requires being "a drop-in replacement for MockWhoopAdapter behind the shared interface" — and `MockWhoopAdapter.get_daily_payload()` (ADR-0011) already combines recovery, cycle, and sleep into one `WhoopDailyPayload`. A recovery-only real adapter couldn't actually replace the mock; `RealWhoopAdapter` calls all 3 endpoints (§2.2-§2.4) to match the contract it must satisfy.

**Retry logic lives inside the adapter; falling back to stale data does not.** §6.1 documents both — "retry after 60 seconds (max 3 retries)" for 429, "retry once after 30 seconds" for 500/503 — and a fallback behavior ("use last stored `daily_metrics` row") when retries are exhausted. Retries are a robustness property of the HTTP call itself, implemented in `RealWhoopAdapter._get()`. The stale-data fallback needs `metrics_repository` access, which the adapter layer doesn't own (ADR-0002: raw→classified translation and remediation decisions belong to the Orchestrator, not adapters) — `RealWhoopAdapter` raises a typed `AdapterError` after retries exhaust (`WhoopRateLimitError`, `WhoopServerError`, `WhoopPendingScoreError`, `WhoopReauthorizationRequiredError`), and the caller (Orchestrator, not yet built) decides whether to fall back to stored data, matching ADR-0010's established pattern.

**Records are validated as they're fetched, not batched at the end.** The first implementation fetched all 3 endpoints before constructing any Pydantic model, meaning a malformed recovery response still cost 2 more WHOOP API calls before the problem was discovered — wasteful against §7.1's documented low-frequency call budget. Fixed to validate each record immediately after its fetch, so a bad recovery response short-circuits before the cycle/sleep calls happen at all.

A related bug caught while writing tests, not a design decision: `_access_token()` originally called `token_repository.needs_refresh()` before checking whether a token existed at all — `needs_refresh()` raises a bare `ValueError` (not an `AdapterError`) when nothing has ever been saved, so an athlete who'd never run `connect-whoop` would hit an unhandled exception instead of a clear error. Fixed to check for a stored token first.

Alternative considered, for the callback mechanism: manual URL paste (print the authorization URL, let the redirect fail with a browser error page, ask the athlete to copy the code out of the address bar). Rejected — a real "this page isn't working" moment in the middle of an otherwise polished CLI flow, for a local server that costs little to implement and is a well-established pattern.
