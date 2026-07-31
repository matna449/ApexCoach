# ApexCoach Web UI (F16.1 scaffolding)

Minimal, local-only web UI: a FastAPI façade over the existing engines/repositories
plus a React frontend. See `docs/adr/0023` for the decision to pull this forward,
scoped explicitly to local-only (no PostgreSQL, no Azure deployment, no
multi-user/auth — that's real v2.0 work).

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
