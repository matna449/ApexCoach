# F21 — Hosted WHOOP Sync on Vercel (webhooks + Postgres)

Status: proposed · Target: v1.5/v2.0 bridge · Supersedes in part: docs/adr/0018 (callback mechanism), docs/adr/0023 ("local-only, no PostgreSQL" scope)

Implementation spec for Claude Code. Every file/module named below exists today unless marked **(new)**. Record the decisions in a new ADR `docs/adr/0028-hosted-whoop-sync-on-vercel.md` **(new)** in the same frontmatter style (`status: accepted`) as 0018/0021.

## 1. Goal

WHOOP data lands in the database automatically, within minutes of WHOOP scoring it, with no process held by a human or an AI agent. The AI health agent only *reads* one compact endpoint each morning and *writes* subjective answers to one endpoint.

```
WHOOP ──webhook──▶ POST /webhooks/whoop ──(verify, record, 2xx)──▶ background fetch v2 API ──▶ upsert daily_metrics (Postgres/Neon)
Vercel Cron (daily) ──▶ GET /api/cron/whoop-reconcile ──▶ re-fetch last 3 local days ──▶ same upsert
AI agent ──Bearer key──▶ GET /api/health/daily?days=N  ·  POST /api/health/subjective
```

Non-negotiables carried over from the repo:
- `web/backend/main.py` stays a façade (web/README.md, ADR-0023): mapping/sync logic lives in `apex_coach/`, not in route handlers.
- `MetricsRepository` / `TokenRepository` remain sole writers (ADR-0003); `daily_metrics` writes are single-statement upserts (ADR-0012).
- Tokens encrypted with Fernet derived from `APEX_ENCRYPTION_KEY` (ADR-0005), unchanged.
- HRV 30-day baseline = `[D-30, D-1]` via `apex_coach/services/hrv_trend.py` (ADR-0021), not reimplemented.
- CLI + SQLite keep working locally; tests stay on SQLite by default.

## 2. Findings in the current code (must-fix before Vercel)

| # | Where | Problem | Fix (phase) |
|---|---|---|---|
| 1 | `apex_coach/db/engine.py` | `create_engine(db_path)` hard-codes `sqlite:///` and always runs `PRAGMA foreign_keys=ON` | Accept a full URL; register the PRAGMA listener only when `url.get_backend_name() == "sqlite"`; for Postgres use `pool_pre_ping=True`, small pool (Neon pooled URL) (F21.1) |
| 2 | `web/backend/main.py:56`, `apex_coach/cli/main.py` (~20 call sites) | `create_engine(settings.database_url.removeprefix("sqlite:///"))` | Pass `settings.database_url` straight through; one helper `get_engine()` (F21.1) |
| 3 | `metrics_repository.py` (`upsert_daily_metrics`, `save_activity`), `token_repository.py` (`save_token`) | `sa.dialects.sqlite.insert(...).on_conflict_do_update` — SQLite-only | Dialect-dispatched insert: `sqlite.insert` / `postgresql.insert` (same `on_conflict_do_update(index_elements=..., set_=...)` API). Small helper `apex_coach/db/upsert.py` **(new)** (F21.1) |
| 4 | `schema.py` `ix_race_goals_one_active` | `sqlite_where=` only → on Postgres it becomes a plain **unique index on status**, i.e. only one COMPLETED/ABANDONED row ever | Add `postgresql_where=race_goals.c.status == "ACTIVE"`; migration `9f2ae50fad4a` uses raw SQL — verify it's valid on PG or make it dialect-aware (F21.1) |
| 5 | `apex_coach/db/migrations/versions/*` | `op.batch_alter_table` (SQLite move-and-copy) | Works on PG (batch is a no-op passthrough there) — keep, but run the full `alembic upgrade head` against PG in CI to prove it (F21.1) |
| 6 | `apex_coach/db/migrations/env.py` | URL only from `alembic.ini` `sqlalchemy.url` | Override from `DATABASE_URL` env when set (F21.1) |
| 7 | All tables | Dates/timestamps stored as `sa.String` (ISO text), PK = UUID string | PG-compatible; **keep** (lexical date comparisons in `get_daily_metrics_range` still correct for `YYYY-MM-DD`). Do not "upgrade" to native types in F21 |
| 8 | `daily_metrics.whoop_rhr_bpm` is `Integer`, WHOOP returns float `resting_heart_rate` | PG rejects/truncates differently than SQLite's dynamic typing | Round explicitly in the mapper (`round()`), keep column `Integer` (F21.4) |
| 9 | `requirements.txt` | No PG driver; `aiosqlite`, `pandas`, `numpy`, `ollama` inflate the function bundle | Add `psycopg[binary]>=3.2`; consider `requirements-vercel.txt` **(new)** or keep single file if bundle < limit (F21.1, F21.2) |
| 10 | `RealWhoopAdapter.get_daily_payload(date)` | Ignores `date`: always fetches `?limit=1` (latest record) | Webhooks/reconcile need by-id and by-range fetches → new methods (F21.4) |
| 11 | `RealWhoopAdapter._get_scored_record` | `time.sleep(600)` on PENDING_SCORE; 429 path sleeps 60 s ×3 | Never block in serverless: new sync path returns "pending", reconcile/next webhook picks it up; cap 429 retries to 1 short wait (F21.4) |
| 12 | `models/pydantic_models.py` `WhoopRecovery/WhoopCycle/WhoopSleep` | `must_be_scored` validator **rejects** non-SCORED → PENDING_SCORE/UNSCORABLE raises `ValidationError` → `AdapterMalformedResponseError` | Check `score_state` on the raw dict *before* model validation in the sync service (don't change validator; CLI relies on it) (F21.4) |
| 13 | `WhoopSleep` model | No `start`/`end`/`nap`/`cycle_id` fields — needed for day mapping | Add optional fields (`start`, `end`, `nap`, `cycle_id`) as `| None = None` so existing fixtures still validate (F21.4) |
| 14 | `daily_metrics` | No `sleep_performance_pct`, no RPE/stress/pain/soreness-text, no WHOOP record ids | New columns (F21.4 and F21.7 migrations, see §4) |
| 15 | `config/settings.py` | `whoop_redirect_uri` default = GitHub Pages copy-paste page; `APEX_ENCRYPTION_KEY` read via `os.environ[...]` at import of `main.py` (module-level `settings = get_settings()`) | New settings fields (§3.2); default redirect unchanged for CLI |
| 16 | `main.py` CORS | `allow_origins=["http://localhost:5173"]` only | Add `APEX_CORS_ORIGINS` env (comma list); new agent endpoints are server-to-server, no CORS needed |
| 17 | `WHOOP_SCOPE` | `"read:recovery read:cycles read:sleep offline"` — no `read:workout` | `workout.*` webhooks are acknowledged and ignored in F21 (no scope change) |
| 18 | `web/backend/main.py` | No authentication on any route (only CORS, which does not stop direct requests). Deploying would publish health data and writes such as `POST /api/plan/week/push`, plus `/docs`, `/redoc` and `/openapi.json` | Default-deny API auth, §3.3 (F21.2) |
| 19 | `cli/main.py:456`, `cli/main.py:479` | intervals.icu key is only read from `oauth_tokens`, stored by the interactive `connect-intervals-icu` | Optional `INTERVALS_ICU_API_KEY` env var that takes precedence, §3.4 (F21.9) |

Existing pieces to **reuse**: `oauth_pkce.generate_pkce_pair/generate_state`, `whoop_adapter.build_authorization_url/exchange_code_for_tokens/refresh_tokens`, `TokenRepository` (encryption), `MetricsRepository.upsert_daily_metrics/get_daily_metrics_range`, `services/hrv_trend.compute_hrv_30d_avg`, `services/health_check` fixed keys (`muscle_soreness`, `subjective_energy`, `sleep_quality_felt`) + `persist_health_check`, `GET /api/health` (liveness), `GET /api/trends/hrv`.

## 3. Deployment (Vercel)

### 3.1 Layout
- Vercel Python runtime, Fluid compute on. Entry: `[tool.vercel] entrypoint = "web.backend.main:app"` in `pyproject.toml`, Vercel's documented setting for a FastAPI app outside its default entrypoint paths; no `api/index.py` or rewrites. Repo root = project root so `apex_coach` is importable.
- `vercel.json` **(new)**:
```json
{
  "functions": { "web/backend/main.py": { "maxDuration": 60 } },
  "crons": [{ "path": "/api/cron/whoop-reconcile", "schedule": "30 5 * * *" }]
}
```
  Cron is UTC: 05:30 UTC = 06:30 CET / 07:30 CEST. Frontend (`web/frontend`) is **not** deployed in F21.
- `.vercelignore` **(new)**: `*.db`, `.env*`, `web/frontend/node_modules`, `docs/*.docx`, tests.
- Migrations are **not** run on cold start. Run `alembic upgrade head` from a GitHub Action / local shell with `DATABASE_URL` = Neon **direct** (unpooled) URL before promoting.

### 3.2 Env vars (Vercel project settings, Production + Preview; never in git)
| Var | Notes |
|---|---|
| `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET` | Secret type. Secret also = webhook HMAC key |
| `WHOOP_REDIRECT_URI` | `https://<app>.vercel.app/auth/whoop/callback` |
| `APEX_ENCRYPTION_KEY` | Same value as local only if you want to migrate tokens; otherwise fresh + reconnect |
| `DATABASE_URL` | Neon pooled URL, injected by Marketplace integration; normalise `postgres://` → `postgresql+psycopg://` in settings |
| `APEX_API_KEY` | Bearer key for every route not listed as public in §3.3 (generate `secrets.token_urlsafe(32)`) |
| `CRON_SECRET` | Vercel sends `Authorization: Bearer $CRON_SECRET` to cron paths; verify it |
| `APEX_ADMIN_KEY` | Guards `/auth/whoop/start` (single-user app; prevents strangers connecting their WHOOP) |
| `APEX_TIMEZONE` | default `Europe/Stockholm` |
| `INTERVALS_ICU_API_KEY` | Optional, Secret type. Personal API key from intervals.icu Settings > API (§3.4). Set it in Vercel only after F21.2 is live |

`Settings` gains: `apex_api_key`, `apex_admin_key`, `cron_secret`, `apex_timezone`, `cors_origins`, `allow_unauthenticated`, `intervals_icu_api_key` (all optional; endpoints fail closed with 503 if their key is unset). `.env.example` updated with placeholders only.

### 3.3 API auth (default-deny)
Applies to every route in the app, existing and new.

- `web/backend/auth.py` **(new)**: `require_api_key` dependency, attached globally with `FastAPI(dependencies=[Depends(require_api_key)])`, so a route added later is protected without further code. Accepts `Authorization: Bearer <APEX_API_KEY>`, compared with `hmac.compare_digest`; missing or wrong → 401.
- Public paths skip the API key check. Match `request.scope["path"]`, the value the router matches on, exactly and never by prefix, because `/api/health/daily` must stay protected:

| Path | Protected by |
|---|---|
| `/api/health` | Nothing. Returns only `{"status": "ok"}` |
| `/webhooks/whoop` | HMAC signature (§6) |
| `/auth/whoop/start` | `APEX_ADMIN_KEY` (§5) |
| `/auth/whoop/callback` | Single-use OAuth `state` (§5) |
| `/api/cron/whoop-reconcile` | `CRON_SECRET` (§8) |

- `/docs`, `/redoc` and `/openapi.json` are registered outside the dependency system, so the global dependency does not cover them. Pass `docs_url=None, redoc_url=None, openapi_url=None` unless `allow_unauthenticated` is active.
- `APEX_API_KEY` unset → 503, unless `APEX_ALLOW_UNAUTHENTICATED=true`. That opt-out exists for local development, where the React frontend sends no key, and is added to `.env.example` and to `apex_coach/tests/conftest.py` so existing web tests keep working.
- The opt-out is ignored when the `VERCEL` env var is present. Do not use `VERCEL` as the only signal for requiring auth: a missing variable must lead to 503, never to an open API.

### 3.4 intervals.icu API key
The key is static and never refreshed, so unlike WHOOP tokens it does not need to live in the database.

- `_intervals_icu_api_key(engine, settings)` **(new helper in `cli/main.py`)**: return `settings.intervals_icu_api_key` when set, else the `oauth_tokens` row. It replaces the lookups in `_build_activity_sync_adapter` and `_build_plan_export_adapter`. `POST /api/plan/week/push` gets it through `_push_week()`.
- Neither present → keep today's `ClickException`, starting with `No intervals.icu API key stored`, and mention the env var as an alternative.
- `connect-intervals-icu` keeps working unchanged. Never log the key.
- **Dependency:** on Vercel the key only enables `POST /api/plan/week/push`, which reads the week's plan from Neon. It does nothing useful there unless plans are in Neon (open question 2). `sync-session` stays CLI-only.

## 4. Database

- Neon via Vercel Marketplace (`vercel integration add neon`). Local dev/tests: SQLite unchanged.
- Migrations **(new)**, one per phase that needs it (§10), via `batch_alter_table` for SQLite parity:
  - `daily_metrics` add: `whoop_sleep_performance_pct Float`, `whoop_recovery_score_state String`, `whoop_sleep_id String`, `whoop_cycle_id String`, `whoop_synced_at String`, `rpe_yesterday Integer` (CHECK 1–10), `soreness_note Text`, `subjective_stress Integer` (CHECK 1–5), `pain_note Text`.
  - New table `oauth_pending_states(state PK String, code_verifier Text (Fernet-encrypted), created_at String)`; rows expire after 10 min.
  - New table `whoop_webhook_events(trace_id PK String, type String, record_id String, received_at String, processed_at String NULL, status String, error Text NULL)` — dedupe + audit; written via a new `WebhookEventRepository` in `apex_coach/db/webhook_repository.py` **(new)**.
- Existing `muscle_soreness`/`subjective_energy`/`sleep_quality_felt` are reused for the 1–5 answers (see §8).
- Data migration (optional): `scripts/sqlite_to_postgres.py` **(new)** copying all tables with `metadata.sorted_tables`; idempotent via upsert.

## 5. OAuth (hosted)

- `GET /auth/whoop/start?key=<APEX_ADMIN_KEY>` → `generate_pkce_pair()`, `generate_state()`, insert `oauth_pending_states`, 302 to `build_authorization_url(..., settings.whoop_redirect_uri, ...)`.
- `GET /auth/whoop/callback?code&state` → atomically `DELETE ... WHERE state=:s RETURNING code_verifier` (reject missing/expired → 400), `exchange_code_for_tokens(...)`, `TokenRepository.save_token("WHOOP", ...)` (same shape as `connect-whoop` in `cli/main.py`), render a minimal "Connected" HTML. Then trigger a 30-day backfill in background (added in F21.5).
- `error=` query param from WHOOP → 400 page with the error, no token write.
- **Manual step:** add `https://<app>.vercel.app/auth/whoop/callback` as a redirect URI and `https://<app>.vercel.app/webhooks/whoop` as the Webhook URL (model version **v2**) in the WHOOP Developer Dashboard. Keep the GitHub Pages URI so the CLI still works.
- Logic in `apex_coach/services/whoop_oauth.py` **(new)**; routes are thin.

### 5.1 Refresh-token rotation under concurrency
WHOOP rotates refresh tokens; two concurrent webhooks refreshing with the same token → second fails → `WhoopReauthorizationRequiredError` and the app is dead until manual reconnect.
- New `TokenRepository.get_valid_access_token(provider, refresh_fn)` **(new method)**:
  1. Read token; if not `needs_refresh` → return.
  2. Open a transaction; Postgres: `SELECT ... FROM oauth_tokens WHERE provider='WHOOP' FOR UPDATE` (SQLite: `BEGIN IMMEDIATE`; SQLAlchemy `with_for_update()` is ignored on SQLite, so set `isolation_level` / execute `BEGIN IMMEDIATE`).
  3. Re-check expiry inside the lock (another worker may have refreshed) → return if fresh.
  4. Call `refresh_fn(refresh_token)`, write new access+refresh tokens in the **same** transaction, commit.
- `RealWhoopAdapter._access_token()` delegates to it. Keep the old `save_token` path for CLI `connect-whoop`.
- If refresh returns 400/401: mark sync status `REAUTH_REQUIRED` (surfaced in `/api/health/daily` meta), never retry in a loop.

## 6. Webhooks — `POST /webhooks/whoop`

1. Read **raw** body (`await request.body()`) before parsing.
2. Verify: `expected = base64(HMAC_SHA256(key=WHOOP_CLIENT_SECRET, msg=X-WHOOP-Signature-Timestamp + raw_body))`; `hmac.compare_digest` with `X-WHOOP-Signature`. Mismatch/missing → 401. *Verified against developer.whoop.com/docs/developing/webhooks on 2026-10-31.* Timestamp is **milliseconds** since epoch.
3. Reject `|now − timestamp| > 5 min` → 401 (WHOOP docs don't specify a window; 5 min is our choice — make it a constant).
4. Parse `{user_id, id, type, trace_id}`. Insert into `whoop_webhook_events` with `ON CONFLICT (trace_id) DO NOTHING`; if it already existed and is `processed` → return 200 immediately (duplicate delivery).
5. Return **200** (target <1 s; WHOOP retries 5× over ~1 h on non-2xx/timeouts), process in background.
6. Processing (`apex_coach/services/whoop_sync.py` **(new)**, `process_event(event)`):
   - `sleep.updated` (id = sleep UUID) → `GET /developer/v2/activity/sleep/{id}`; if `nap` → ignore; else map day (§7), then `GET /developer/v2/recovery` for that sleep's cycle (`GET /developer/v2/cycle/{cycle_id}/recovery`) and upsert sleep + recovery fields.
   - `recovery.updated` (v2 id = **sleep UUID**, not cycle id) → same as above (fetch sleep → cycle_id → recovery).
   - `sleep.deleted` / `recovery.deleted` → null the WHOOP sleep/recovery columns for the row whose `whoop_sleep_id == id` (don't delete the row; subjective data may live there).
   - `workout.*` → status `ignored`.
   - Strain: **no cycle webhook exists**. After any sleep/recovery event also fetch `GET /developer/v2/cycle?start=<now-48h>` and upsert strain for affected dates (§7).
   - `score_state`: `PENDING_SCORE` → write nothing for that metric, event status `pending`; `UNSCORABLE` → store state, metrics null. Check on raw dict before Pydantic (finding #12).
   - Upserts go through `MetricsRepository.upsert_daily_metrics` → idempotent by `date`.

**Background mechanism — decision:** FastAPI `BackgroundTasks` on Fluid compute (runs after response in the same instance; Vercel keeps the function alive until it finishes, within `maxDuration`). Justification: volume is ~3–6 events/day for one user, each job is 2–4 WHOOP GETs (<5 s); the event row is persisted *before* 2xx, so a crashed background job is recoverable (`status != processed`) and the daily reconcile re-fetches anyway. Vercel Queues would add a second consumer function, topic config and at-least-once semantics we already get from WHOOP retries + reconcile — not worth it at this scale. **Claude Code must verify** that the current Vercel Python runtime honours post-response background work (else use `waitUntil` equivalent from `vercel` Python helpers, or fall back to synchronous processing — still <~5 s, acceptable since WHOOP times out later than that; record whichever in ADR-0028). Revisit Queues only if multi-user (v2.0).

## 7. Day mapping (from real data — encode as pure functions in `apex_coach/services/whoop_day_mapping.py` **(new)**)

- `TZ = ZoneInfo(settings.apex_timezone)` (Europe/Stockholm; DST-aware — never a fixed +1).
- **Sleep & recovery** → `date = local_date(sleep.end)` of the main sleep (`nap == false`). Recovery inherits the date of its sleep. If two non-nap sleeps end on the same local date, keep the one with the longest duration.
- **Cycle strain** → `date = local_date(cycle.start + 6h)`. Cycles start at sleep onset, often before midnight; +6 h pushes 22:30 starts onto the next day.
- Cycle with `end == null` is **today, in progress**: store strain, but `/api/health/daily` marks it `strain_in_progress: true`.
- `sleep_hours` = (in_bed − awake) as in `WhoopSleepScore.total_sleep_hours`; `sleep_performance_pct` = `sleep_performance_percentage`.
- `rhr` rounded to int (finding #8).

## 8. Agent endpoints (Bearer `APEX_API_KEY`, `hmac.compare_digest`; 401 otherwise)

### `GET /api/health/daily?days=N` (1 ≤ N ≤ 90, default 14)
Response:
```json
{
  "generated_at": "2026-10-31T07:00:00+01:00",
  "sync": {"status": "OK|REAUTH_REQUIRED|STALE", "last_synced_at": "...", "pending_events": 0},
  "days": [{
    "date": "2026-10-31",
    "recovery_pct": 33, "hrv_ms": 51.5, "resting_hr_bpm": 54,
    "sleep_hours": 6.5, "sleep_performance_pct": 71, "strain": 4.2, "strain_in_progress": true,
    "hrv_7d_avg": 75.8, "hrv_30d_avg": 72.1, "rhr_7d_avg": 46.6,
    "subjective": {"rpe_yesterday": 3, "soreness": null, "sleep_quality": 2, "energy": 5, "stress": 1, "pain": null},
    "flags": ["RECOVERY_RED", "HRV_BELOW_7D_20PCT"]
  }]
}
```
- Averages use prior days only (`[D-7, D-1]`, `[D-30, D-1]`), consistent with ADR-0021; `hrv_30d_avg` via `compute_hrv_30d_avg`. Null when < 3 samples (7d) / < 7 samples (30d, ADR-0021 min).
- Flags: `RECOVERY_RED` (recovery < 34, matches CONTEXT.md band), `HRV_BELOW_7D_20PCT` (hrv < 0.8 × hrv_7d_avg), `LOW_RECOVERY_3D` (recovery < 34 on D, D-1, D-2), `SYNC_STALE` (no WHOOP data for today after 10:00 local).
- Computation in `apex_coach/services/health_summary.py` **(new)**; pure function over rows from `get_daily_metrics_range`.

### `POST /api/health/subjective`
```json
{"date": "2026-10-31", "rpe_yesterday": 3, "soreness": "none", "sleep_quality": 2, "energy": 5, "stress": 1, "pain": null}
```
- Existing model covers part: `sleep_quality` → `sleep_quality_felt` (1–5), `energy` → `subjective_energy` (1–5). `muscle_soreness` is a **1–5 integer** used by the Daily Engine's Soreness Band; free-text soreness goes to `soreness_note`, and optional `soreness_level` (1–5) maps to `muscle_soreness`. `rpe_yesterday`, `stress`, `pain` → new columns (§4). Do **not** fabricate `health_check_json` (that's the session-adaptive check, ADR-0012).
- Validation: Pydantic; RPE 1–10, others 1–5; partial updates allowed (only provided fields upserted). `date` defaults to today in `APEX_TIMEZONE`.
- Single `upsert_daily_metrics` call → doesn't clobber WHOOP columns.

### Other routes
- `GET /api/cron/whoop-reconcile` (Bearer `CRON_SECRET`): for local dates today−2…today, fetch `GET /developer/v2/activity/sleep?start=&end=`, `/developer/v2/recovery?start=&end=`, `/developer/v2/cycle?start=&end=` (paginate `next_token`), map + upsert; reprocess `whoop_webhook_events` stuck in `received`/`pending`; purge `oauth_pending_states` older than 10 min. Returns counts. Also callable with `?days=30` for backfill (cap 30).
- Existing `GET /api/health` stays the unauthenticated liveness probe (note: name collides conceptually with `/api/health/*`; keep it, document it).

## 9. Tests (pytest + pytest-httpx; all against SQLite unless marked)

- `test_whoop_webhook_signature.py`: valid sig → 200; tampered body → 401; wrong secret → 401; missing headers → 401; timestamp ±6 min → 401; signature computed over **raw** bytes (whitespace-different JSON fails).
- `test_whoop_webhook_idempotency.py`: same `trace_id` twice → one processing, one WHOOP fetch (httpx mock call count); two different events for same day → single `daily_metrics` row; replay after processing → no-op.
- `test_token_refresh_race.py`: two threads calling `get_valid_access_token` with an expired token → `refresh_tokens` mocked endpoint hit **exactly once**, both get the new access token; refresh 400 → `REAUTH_REQUIRED`. Run on SQLite (`BEGIN IMMEDIATE`) and, marked `postgres`, on PG.
- `test_whoop_day_mapping.py`: sleep ending 06:40 local → that date; sleep 23:10→07:00 across midnight → end date; nap ignored; cycle start 22:30 local → next date; cycle start 01:00 → same date; DST transition days (2026-03-29, 2026-10-25); `end=null` → in progress.
- `test_whoop_sync_pending_score.py`: PENDING_SCORE → no metric write, event `pending`; later reconcile with SCORED → written; UNSCORABLE → null + state stored. No `sleep()` calls (assert injected `sleep_fn` unused).
- `test_whoop_oauth_hosted.py`: start stores state+encrypted verifier, 302 to WHOOP with S256 challenge; callback with unknown/expired state → 400; valid → token saved encrypted; state single-use.
- `test_health_summary.py` / `test_web_backend_health_daily.py`: averages exclude D; flags edge cases (recovery 34 not red, exactly −20 %); 3-day streak; auth 401; `days` bounds.
- `test_web_backend_health_subjective.py`: partial update keeps WHOOP columns; RPE 11 → 422.
- `test_upsert_dialects.py`: compiled SQL for both dialects; `ix_race_goals_one_active` has a WHERE on PG.
- `test_web_backend_auth.py`: walk `app.routes` and assert every route outside the public list returns 401 without a key and with a wrong key (so a future route cannot slip through); valid key passes; `/api/health/daily` is not treated as public; `/docs`, `/redoc`, `/openapi.json` → 404 without the opt-out; key unset → 503; key unset + opt-out → open; opt-out + `VERCEL=1` → 503.
- `test_intervals_icu_api_key.py`: env var wins over stored token; falls back to stored token; neither → existing `ClickException`, mapped to 400 by `POST /api/plan/week/push`.
- CI job `postgres` (GitHub Actions service container `postgres:16`): `alembic upgrade head` + `downgrade base` + repository integration tests with `DATABASE_URL` set. Marker `postgres`, skipped locally unless `--run-postgres` (mirror existing `live_llm` marker pattern in `pyproject.toml` / `conftest.py`).

## 10. Phases (one PR each)

**F21.1 — Dialect-agnostic DB layer.** Findings #1–#7, settings URL normalisation, upsert helper, race_goals PG partial index, alembic env reads `DATABASE_URL`, `psycopg` dep, PG CI job.
*Accept:* full test suite green on SQLite; `alembic upgrade head` then `downgrade base` green on PG 16; CLI unchanged.

Each phase is a vertical slice that can be verified on its own. Phases that add a migration must leave Alembic with a single head.

**F21.2 — API auth + first preview.** Blocked by F21.1. Finding #18, §3.3, the `pyproject.toml` entrypoint, `vercel.json` without the cron, `.vercelignore`, Neon via Marketplace, migrations run, env vars set in Vercel (not git). Nothing may be deployed before this PR's auth is in place, because the later phases test against a deployed preview.
*Accept:* auth tests green; local frontend works with the opt-out; on the preview URL `GET /api/health` → 200, `GET /api/trends/hrv` and `POST /api/plan/week/push` → 401 without a key, and `/docs` → 404.

**F21.3 — Hosted WHOOP connection.** Blocked by F21.2. `oauth_pending_states` migration, `/auth/whoop/start`, `/auth/whoop/callback`, `TokenRepository.get_valid_access_token` with row lock, settings keys, ADR-0028 draft, ADR-0018 note "superseded for hosted deploy".
*Accept:* OAuth and refresh-race tests green; `whoop-smoke --real` still works; manual: connect from deployed preview, token row in Neon encrypted.

**F21.4 — Webhook to `daily_metrics`.** Blocked by F21.3. Migration for the WHOOP columns on `daily_metrics` and `whoop_webhook_events`; `WebhookEventRepository`; `WhoopSleep` optional fields; `whoop_day_mapping.py`; `whoop_sync.py` (by-id + by-range fetch, pending/unscorable handling, no blocking sleeps); `/webhooks/whoop` with signature/timestamp check, dedupe, background processing.
*Accept:* migration round-trips on both dialects; existing fixtures still validate; day-mapping, pending-score, signature and idempotency tests green; manual: edit a sleep by 1 min in the WHOOP app → `daily_metrics` row updated within 2 min.

**F21.5 — Reconcile cron + backfill.** Blocked by F21.4. `/api/cron/whoop-reconcile`, `vercel.json` cron, `CRON_SECRET` check, 30-day backfill triggered by the OAuth callback.
*Accept:* deleting today's WHOOP columns then calling cron restores them; unauthenticated call → 401; `?days=30` backfills.

**F21.6 — Agent read API.** Blocked by F21.4 and F21.7, because the `subjective` block reads F21.7's columns. `/api/health/daily`, `health_summary.py`.
*Accept:* tests green; response for 14 days < 4 KB; flags match fixtures.

**F21.7 — Agent write API.** Blocked by F21.2. Migration for `rpe_yesterday`, `soreness_note`, `subjective_stress`, `pain_note`; `/api/health/subjective`.
*Accept:* tests green; migration round-trips on both dialects; a partial update keeps WHOOP columns.

**F21.8 — Production deploy.** Blocked by F21.3–F21.7. Promote to production, WHOOP dashboard updated, `web/README.md` + root README "Hosted deployment" section.
*Accept:* production URL: `GET /api/health` 200; connect flow done; one real webhook processed; next-morning cron logs OK; `GET /api/health/daily?days=7` returns today's recovery without any manual action; the F21.2 401 checks pass on the production URL.

**F21.9 — intervals.icu key from env.** No blockers for the code. Finding #19, §3.4, `.env.example` placeholder. Requires F21.2 before the key is set in Vercel.
*Accept:* `test_intervals_icu_api_key.py` green; `connect-intervals-icu` flow still works; with only `INTERVALS_ICU_API_KEY` set, `sync-session --real` works locally.

## 11. Out of scope
- Deploying the React frontend (it sends no key, and a browser cannot safely hold `APEX_API_KEY`; hosting it needs its own login); multi-user / per-user token rows (`oauth_tokens.provider` is UNIQUE — single athlete by design, ADR-0023).
- Strava/intervals.icu webhooks; workouts (`read:workout` scope).
- Running the Daily Engine / Ollama explanation on Vercel (Ollama is local-only).
- Native `DATE`/`TIMESTAMPTZ` column types; Vercel Queues.

## 12. Open questions
1. Token migration: copy the encrypted local `oauth_tokens` row (needs same `APEX_ENCRYPTION_KEY`) or just reconnect via hosted flow? (Recommend reconnect — there is currently no local `.env`/DB anyway.)
2. Should the CLI also read/write Neon (single source of truth) or keep a separate local SQLite? Two DBs will diverge.
3. Webhook timestamp tolerance: 5 min OK? (WHOOP docs give none; their retries resend with a new timestamp — confirm.)
4. Does the agent need `spo2`/`skin_temp` (already in `WhoopRecoveryScore`) in the daily endpoint?
5. Is `/auth/whoop/start` guarded by `APEX_ADMIN_KEY` query param acceptable, or use Vercel Deployment Protection on that path?
6. Should a "STALE"/"REAUTH_REQUIRED" state push a notification (email) rather than wait for the agent's next read?
