"""FastAPI façade over the existing ApexCoach engines/repositories (F16.1, docs/adr/0023).

This app does not duplicate or reimplement any decision/business logic. It is a
thin HTTP layer that will, in later tickets (F16.2+), call the same
`MetricsRepository` / `PlanRepository` / engine functions the CLI already uses
against the same SQLite database. This ticket only proves the plumbing works
end-to-end with a single trivial round trip (`GET /api/health`).

Run from the repo root so `apex_coach` resolves on the Python path (mirrors
`pythonpath = ["."]` in pyproject.toml's pytest config):

    uvicorn web.backend.main:app --reload --port 8000

Config is loaded the exact same way the CLI loads it — see
`apex_coach/config/settings.py` and `apex_coach/cli/main.py`
(`create_engine(settings.database_url.removeprefix("sqlite:///"))`). Endpoint
handlers added by later tickets should follow that same pattern, e.g.:

    from apex_coach.config.settings import get_settings
    from apex_coach.db.engine import create_engine
    from apex_coach.db.metrics_repository import MetricsRepository

    settings = get_settings()
    engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
    repo = MetricsRepository(engine)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apex_coach.config.settings import get_settings

# Loaded at import time so a missing APEX_ENCRYPTION_KEY (or other required
# env var) fails fast on startup, exactly like the CLI does — not used yet,
# but confirms the config-loading pattern is wired up correctly for later
# tickets to build on.
get_settings()

app = FastAPI(title="ApexCoach Web API")

# Local dev only (SDD roadmap: v2.0 is the real multi-user/Azure milestone).
# Allows the Vite dev server's default origin to call this API directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
