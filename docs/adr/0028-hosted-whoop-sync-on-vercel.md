---
status: proposed
---

# Hosted WHOOP sync on Vercel: FastAPI function, Neon, default-deny auth, server-side OAuth

Draft, finished in F21.8. The spec is docs/specs/F21_Vercel_WHOOP_Sync_Spec.md. This narrows the "local-only, no PostgreSQL" scope in docs/adr/0023 and adds a hosted callback next to docs/adr/0018.

**One FastAPI function, no frontend.** The React frontend sends no key and a browser cannot safely hold `APEX_API_KEY`, so hosting it would need its own login. `tool.vercel.entrypoint` in `pyproject.toml` selects `web.backend.main:app`. Vercel then installs from `pyproject.toml`, not `requirements.txt`, so `[project].dependencies` lists the runtime packages and the CI job `vercel-deps` imports the app with only those.

**Every route needs a key unless it is on an exact public list.** The dependency sits on the whole app, so later routes are covered. A missing key gives 503. The local opt-out is ignored when `VERCEL` is present.

**The OAuth state lives in the database.** Serverless instances share nothing, so `/auth/whoop/start` and the callback meet in `oauth_pending_states`. The verifier is encrypted, rows expire after 10 minutes, and an atomic delete makes the state single-use.

**Token refresh takes a row lock across the HTTP call.** WHOOP rotates refresh tokens, so the second of two concurrent refreshes would be rejected and force a new connection. The lock holds a database connection for the length of one WHOOP request, which is acceptable at a few requests per day. Postgres uses `FOR UPDATE`, SQLite `BEGIN IMMEDIATE`.

**A rejected refresh token is remembered.** A 400 or 401 sets `oauth_tokens.sync_status` to `REAUTH_REQUIRED`, and later calls fail without contacting WHOOP until a new `save_token`. Other refresh failures, such as a WHOOP 500, change nothing, because the token may still be good.

**Webhooks are processed synchronously, inside the request.** Vercel's FastAPI docs point to Queues and Workflows for background work and do not say that `BackgroundTasks` keeps running after the response, so relying on it could silently lose work. One event is 2 to 4 WHOOP GETs, and each one has a 5-second timeout. The event row is written first, a failure still answers 200, and the daily reconcile fetches the data again. If WHOOP starts timing out or retrying, Queues is the next step.

**The sync never waits long.** A record that is not scored yet writes nothing and is left for the next event or the reconcile. A 429 gets one 2-second wait. The CLI keeps its long waits.

**Deployment Protection stays on Standard.** It covers previews and leaves the production domain open. WHOOP's redirect and webhooks use that domain, and the app's own auth protects it.
