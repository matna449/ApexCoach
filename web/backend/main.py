"""FastAPI façade over the existing ApexCoach engines/repositories (F16.1, docs/adr/0023).

This app does not duplicate or reimplement any decision/business logic. It is a
thin HTTP layer that calls the same `MetricsRepository` / `PlanRepository` /
engine functions the CLI already uses, against the same SQLite database.

Run from the repo root so `apex_coach` resolves on the Python path (mirrors
`pythonpath = ["."]` in pyproject.toml's pytest config):

    uvicorn web.backend.main:app --reload --port 8000

Config is loaded the exact same way the CLI loads it — see
`apex_coach/config/settings.py` and `apex_coach/cli/main.py`
(`create_engine(settings.database_url.removeprefix("sqlite:///"))`). Endpoint
handlers added by later tickets should follow that same pattern.
"""

from datetime import date, timedelta

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from apex_coach.config.settings import get_settings
from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository

# Loaded at import time so a missing APEX_ENCRYPTION_KEY (or other required
# env var) fails fast on startup, exactly like the CLI does.
settings = get_settings()
engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
repo = MetricsRepository(engine)

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


DEFAULT_TREND_WINDOW_DAYS = 30


@app.get("/api/trends/hrv")
def hrv_trend(
    start: str | None = Query(
        default=None, description="Inclusive start date, YYYY-MM-DD."
    ),
    end: str | None = Query(
        default=None, description="Inclusive end date, YYYY-MM-DD."
    ),
) -> list[dict]:
    """Real `whoop_hrv_ms` readings over an inclusive date range, via
    `MetricsRepository.get_daily_metrics_range()`.

    `start`/`end` are optional ISO date strings (YYYY-MM-DD). If omitted,
    defaults to the trailing 30 days (today minus 29 days through today).
    Returns a list of `{"date": str, "whoop_hrv_ms": float | None}`, ordered
    by date, one entry per `daily_metrics` row in range (rows with no HRV
    reading yet still appear, with `whoop_hrv_ms: null`, so the frontend can
    tell "no row that day" apart from "empty range" if it ever needs to).
    """
    if end is None:
        end = date.today().isoformat()
    if start is None:
        start = (date.today() - timedelta(days=DEFAULT_TREND_WINDOW_DAYS - 1)).isoformat()

    rows = repo.get_daily_metrics_range(start, end)
    return [{"date": row["date"], "whoop_hrv_ms": row["whoop_hrv_ms"]} for row in rows]
