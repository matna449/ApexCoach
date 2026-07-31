---
status: accepted
---

# RealStravaAdapter: reuse WHOOP's hosted-callback OAuth flow, no PKCE, short-page pagination, 404 maps to None not an exception

Building F02.2 (#10) turned API Contract §3.1's OAuth flow and §3.2-§3.3/§6.2's endpoint and failure specs into working code. Before implementing, the contract itself was audited against developers.strava.com (see the accompanying docx correction) and found two path bugs of the same shape ADR-0018 found for WHOOP — caught this time from docs, not a live 404.

**No PKCE.** Strava's OAuth 2.0 Authorization Code flow doesn't support or require PKCE (confirmed via developers.strava.com/docs/authentication) — `run_authorization_flow()` calls `generate_state()` only, not `generate_pkce_pair()`, and `exchange_code_for_tokens()`/`refresh_tokens()` take no `code_verifier`.

**Redirect URI reuses the same hosted GitHub Pages callback page as WHOOP, even though Strava allows localhost.** Strava explicitly whitelists `localhost`/`127.0.0.1` redirect URIs (unlike WHOOP, which rejects them outright). The athlete chose to reuse the same paste-the-code-back flow anyway, for consistency between the two providers' setup experience rather than building two different callback mechanisms. `oauth_pkce.py`'s `generate_state()` (already provider-agnostic per ADR-0018) is the only shared piece needed since there's no PKCE.

**Two path corrections mirroring ADR-0018's WHOOP findings, caught via docs audit before implementing:** the token exchange/refresh endpoint is `https://www.strava.com/api/v3/oauth/token`, not `https://www.strava.com/oauth/token` (the authorize endpoint is correctly un-prefixed); and `/api/v3` is already the adapter's `httpx.Client` base URL, so endpoint paths are `/athlete/activities` and `/activities/{id}/streams`, not `/v3/athlete/activities` — the old paths would have double-counted the version segment exactly like WHOOP's `/developer/` prefix bug.

**Pagination stops on a short page, not an empty one.** `get_new_activities()` requests `per_page=30` and keeps incrementing `page` until a response has fewer than 30 records — a full page always means "there might be more," an empty or partial page always means "that was the last one." An empty-page-only stop condition would work too but costs one extra request per sync in the common case (last page happens to have exactly 30 items).

**404 on the streams endpoint returns `None`, not an exception.** `StravaAdapterProtocol.get_activity_stream()` already returns `StravaStream | None` (`MockStravaAdapter` returns `None` for an unknown `activity_id`) — a real 404 (activity deleted or made private between listing and stream fetch) is the same "no stream to give you" case, so `RealStravaAdapter` raises an internal `StravaActivityNotFoundError`, catches it one level up, and converts it to `None` rather than surfacing it as an `AdapterError` the caller has to handle specially. §6.2's "mark record as STRAVA_DELETED, do not retry" is about the *caller's* database bookkeeping (matching ADR-0018's precedent: adapters classify failures, callers own remediation), not something this method does itself.

**429 retries 3x at 15 minutes, matching WHOOP's pattern.** §6.2's table said "back off and retry after 15 minutes" without a count — WHOOP's equivalent row explicitly said "max 3 retries." Confirmed with the athlete: match WHOOP's count for consistency (up to 45 minutes total before giving up), rather than inventing a different number from an ambiguous table.

**Strava's rotating refresh token is read as a required field, not defaulted to the old one.** §3.1's STEP 4/5 are explicit: "every time you get a new access token, we return a new refresh token as well," and using a stale one after rotation fails. `_access_token()` reads `response["refresh_token"]` directly (`KeyError` if Strava ever violates this) rather than `response.get("refresh_token", token["refresh_token"])` (WHOOP's pattern, where the refresh token doesn't necessarily rotate) — a loud failure here is safer than a stored token that silently stops working.

**`expires_at` is read directly from Strava's response, not computed from `expires_in` + `now()`.** Unlike WHOOP (which only returns `expires_in`), Strava's token responses include both `expires_at` (Unix timestamp) and `expires_in` (seconds) — using the provider's own timestamp avoids clock skew between when the response was generated and when this process observes it.
