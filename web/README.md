# ApexCoach Web UI (F16.1 scaffolding)

Minimal, local-only web UI: a FastAPI façade over the existing engines/repositories
plus a React frontend. See `docs/adr/0023` for the decision to pull this forward,
scoped explicitly to local-only (no PostgreSQL, no Azure deployment, no
multi-user/auth — that's real v2.0 work). F21 later added a single-user hosted
backend, see [Hosted deployment](#hosted-deployment).

This ticket (#66) is scaffolding only: it proves the plumbing works end-to-end
with one trivial round trip (`GET /api/health`). It does not add any real
screens — those land in follow-up tickets (#68/#69/#70).

**The FastAPI backend is a pure façade.** It must never duplicate or
reimplement decision/business logic — only call the existing
`apex_coach` engines/repositories over HTTP. The existing CLI
(`apex_coach` console script) is unaffected and keeps working exactly as
before; this is purely additive.

## Layout

```
web/
  backend/
    main.py       # FastAPI app: GET /api/health, CORS for the Vite dev server
  frontend/        # React + Vite + TypeScript (npm create vite -- --template react-ts)
    src/App.tsx    # fetches GET /api/health and renders the response
```

## Running locally

You need three things running side by side for full local dev: the existing
CLI/DB (unaffected by any of this), the backend, and the frontend.

### 1. Backend (FastAPI + uvicorn)

Dependencies are in the repo-root `requirements.txt` (`fastapi`, `uvicorn[standard]`
were added there rather than a separate `web/backend/requirements.txt` — this is a
small façade over the same codebase/venv the CLI already uses, so one requirements
file avoids drift between two dependency lists that both describe the same Python
environment).

```bash
# from the repo root, with your existing venv activated
pip install -r requirements.txt

# .env must already have APEX_ENCRYPTION_KEY set (same as the CLI — see
# .env.example / root README). DATABASE_URL is read the same way the CLI
# reads it, via apex_coach.config.settings.get_settings().
uvicorn web.backend.main:app --reload --port 8000
```

The API denies every request unless `.env` has `APEX_ALLOW_UNAUTHENTICATED=true`
(the frontend sends no key, see `.env.example`) or the request carries
`Authorization: Bearer <APEX_API_KEY>`. Only `GET /api/health` is open.

Run uvicorn from the **repo root** — that's what puts `apex_coach` on the Python
path (mirrors `pythonpath = ["."]` in `pyproject.toml`'s pytest config; no separate
`sys.path` hacking needed).

Verify:

```bash
curl http://localhost:8000/api/health
# {"status":"ok"}
```

### 2. Frontend (React + Vite + TypeScript)

```bash
cd web/frontend
npm install
npm run dev
```

Open `http://localhost:5173` — the page fetches `http://localhost:8000/api/health`
directly from the browser and renders the JSON response.

### 3. CLI / DB

Unaffected — keep using `apex_coach <command>` exactly as documented in the root
README. The web backend reads the same SQLite database via the same
`DATABASE_URL` / `create_engine()` pattern; run `apex_coach init-db` first if you
haven't already.

## Design choices made in this ticket

- **CORS, not a dev-server proxy**: the frontend calls the backend directly at
  `http://localhost:8000` and the backend's `CORSMiddleware` allowlists
  `http://localhost:5173` (Vite's default dev port). This was chosen over a Vite
  proxy (`server.proxy` in `vite.config.ts`) so the CORS acceptance criterion is
  actually exercised by the round trip rather than sitting configured-but-unused.
  If a later ticket wants to switch to a proxy, only `App.tsx`'s `API_BASE_URL`
  and `vite.config.ts` need to change — the backend's CORS config can stay as a
  fallback for direct calls (e.g. from tools, or during transition).
- **Flat backend layout**: `web/backend/main.py` is a single file. This is a
  small façade, not a growing service — later tickets adding real endpoints can
  split it into an `app/` package if `main.py` gets unwieldy, but there was no
  reason to pre-build that structure for one health-check route.
- **Dependencies in the root `requirements.txt`**, not a separate
  `web/backend/requirements.txt` — see the "Backend" section above.

## Hosted deployment

`web.backend.main:app` runs as one Vercel function on Python 3.12 (`tool.vercel.entrypoint` in `pyproject.toml`). Decisions are in `docs/adr/0028`, and the full design is in `docs/specs/F21_Vercel_WHOOP_Sync_Spec.md`. The local setup above is unaffected.

### Routes

| Route | Protected by |
|---|---|
| `GET /api/health` | Nothing, liveness only |
| `POST /webhooks/whoop` | WHOOP's HMAC signature |
| `GET /auth/whoop/start?key=` | `APEX_ADMIN_KEY` |
| `GET /auth/whoop/callback` | Single-use OAuth state |
| `GET /api/cron/whoop-reconcile?days=` | `CRON_SECRET` |
| Everything else, including `GET /api/health/daily` and `POST /api/health/subjective` | `Authorization: Bearer <APEX_API_KEY>` |

A missing key gives 503, never an open route. `/docs`, `/redoc` and `/openapi.json` are 404 on Vercel.

### Environment variables

Set these for Production and Preview, and never commit them. Vercel stores them as Secrets by default, which cannot be read back, so keep your own copy of the keys you generate.

| Variable | Notes |
|---|---|
| `DATABASE_URL` | Pooled URL, added by the Neon integration |
| `APEX_ENCRYPTION_KEY` | Encrypts stored tokens. Changing it means reconnecting WHOOP |
| `APEX_API_KEY` | For the agent, `secrets.token_urlsafe(32)` |
| `APEX_ADMIN_KEY` | Starts the WHOOP connection |
| `CRON_SECRET` | Vercel sends it to the cron route |
| `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET` | The secret also verifies webhooks |
| `WHOOP_REDIRECT_URI` | `https://<app>.vercel.app/auth/whoop/callback` |
| `APEX_TIMEZONE` | Optional, default `Europe/Stockholm` |
| `INTERVALS_ICU_API_KEY` | Optional, only useful once plans are in Neon |

### First setup

1. Import the repository in Vercel as FastAPI, with root directory `./`.
2. Connect a Neon database from the project's **Storage** tab.
3. Keep **Deployment Protection** on **Standard Protection**. WHOOP has to reach the production domain, and **All Deployments** would block it.
4. Set the variables above and redeploy.
5. Run the migrations (below).
6. In the WHOOP Developer Dashboard, add the redirect URI. Keep the GitHub Pages one, because the CLI uses it. Set the webhook URL to `https://<app>.vercel.app/webhooks/whoop`, with model version v2.
7. Open `https://<app>.vercel.app/auth/whoop/start?key=<APEX_ADMIN_KEY>` and approve. Connecting also backfills 30 days.

### Migrations

Migrations never run on deploy. Run them from a shell before merging a change that needs them, with Neon's **direct** URL, whose host has no `-pooler`:

```bash
read -rs "DB?Direct Neon URL: "; echo; DATABASE_URL="$DB" .venv/bin/alembic upgrade head; DATABASE_URL="$DB" .venv/bin/alembic current; unset DB
```

### Operations

- **Daily cron:** runs at 05:30 UTC and re-fetches the last three local days. Call it with `?days=30` to backfill (capped at 30).
- **Sync state:** `sync.status` in `GET /api/health/daily` is `OK`, `STALE` or `REAUTH_REQUIRED`.
- **`REAUTH_REQUIRED`:** WHOOP rejected the refresh token, or no token exists. Open the start link again.
- **Logs:** `npx vercel logs` shows function output. WHOOP URLs appear there, and health values do not.

