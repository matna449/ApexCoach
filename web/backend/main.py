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

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from apex_coach.config.settings import get_settings
from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository

# Loaded at import time so a missing APEX_ENCRYPTION_KEY (or other required
# env var) fails fast on startup, exactly like the CLI does — also gives us
# the database_url used to build the engine/repo below.
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


@app.get("/api/execution-score-trend")
def execution_score_trend(
    start_date: str = Query(..., description="YYYY-MM-DD, inclusive"),
    end_date: str = Query(..., description="YYYY-MM-DD, inclusive"),
) -> dict:
    """F16.4: execution_score over time + overpush/underpush counts.

    Reads `activities` + `session_scores` via `MetricsRepository`, mirroring
    the combine pattern in `apex_coach.engines.monthly_engine.run_monthly_review`
    (for each activity in range, fetch its most recent session_scores row and
    keep the ones that have one).
    """
    activities = repo.get_activities_range(start_date, end_date)

    points = []
    overpush_count = 0
    underpush_count = 0
    for activity in activities:
        score = repo.get_session_score(activity["id"])
        if score is None:
            continue
        points.append(
            {
                "date": activity["date"],
                "activity_id": activity["id"],
                "activity_type": activity.get("activity_type"),
                "intended_session_type": activity.get("intended_session_type"),
                "execution_score": score.get("execution_score"),
                "overpush_flag": bool(score.get("overpush_flag")),
                "underpush_flag": bool(score.get("underpush_flag")),
            }
        )
        if score.get("overpush_flag"):
            overpush_count += 1
        if score.get("underpush_flag"):
            underpush_count += 1

    return {
        "start_date": start_date,
        "end_date": end_date,
        "points": points,
        "overpush_count": overpush_count,
        "underpush_count": underpush_count,
    }
