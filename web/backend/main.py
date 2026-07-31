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

from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apex_coach.config.settings import get_settings
from apex_coach.db.engine import create_engine
from apex_coach.db.plan_repository import PlanRepository

# Loaded at import time so a missing APEX_ENCRYPTION_KEY (or other required
# env var) fails fast on startup, exactly like the CLI does — not used yet,
# but confirms the config-loading pattern is wired up correctly for later
# tickets to build on.
settings = get_settings()
engine = create_engine(settings.database_url.removeprefix("sqlite:///"))
repo = PlanRepository(engine)

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


# -- F16.3: load actual vs. target (weekly + monthly) -----------------------
#
# PlanRepository has no "get a range of weeks/months" method, only a
# single-row lookup by exact period-start date (get_weekly_plan /
# get_monthly_target). These endpoints accept an explicit, comma-separated
# list of period-start dates via a query param — the caller picks exactly
# which weeks/months it wants — and fall back to computing N trailing
# periods ending at the current week/month when no explicit list is given,
# which is what the chart page uses by default. Missing rows (no plan/target
# recorded for that period yet) are returned with null actual/target rather
# than omitted, so the chart can still render a gap for that period.


def _monday_on_or_before(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _trailing_week_starts(count: int) -> list[str]:
    """ISO date strings for `count` Mondays, oldest first, ending at the
    Monday of the current week."""
    current_monday = _monday_on_or_before(date.today())
    return [
        (current_monday - timedelta(weeks=offset)).isoformat()
        for offset in range(count - 1, -1, -1)
    ]


def _trailing_month_starts(count: int) -> list[str]:
    """ISO date strings for the 1st of `count` months, oldest first, ending
    at the 1st of the current month."""
    today = date.today()
    starts: list[str] = []
    for offset in range(count - 1, -1, -1):
        month_index = today.month - 1 - offset  # 0-based, may be negative
        year = today.year + month_index // 12
        month = month_index % 12 + 1
        starts.append(date(year, month, 1).isoformat())
    return starts


@app.get("/api/load/weekly")
def load_weekly(
    week_start_dates: str | None = None, weeks: int = 8
) -> dict[str, list[dict]]:
    """Load actual vs. target per week.

    Query params:
    - `week_start_dates`: optional comma-separated list of ISO Monday dates,
      e.g. `2026-06-01,2026-06-08`. When given, exactly these weeks are
      returned (in the order given).
    - `weeks`: when `week_start_dates` is omitted, the number of trailing
      weeks (ending at the current week) to return. Default 8.
    """
    dates = (
        [d.strip() for d in week_start_dates.split(",") if d.strip()]
        if week_start_dates
        else _trailing_week_starts(weeks)
    )
    result = []
    for week_start_date in dates:
        row = repo.get_weekly_plan(week_start_date)
        result.append(
            {
                "week_start_date": week_start_date,
                "load_actual": row["load_actual"] if row else None,
                "load_target": row["load_target"] if row else None,
            }
        )
    return {"weeks": result}


@app.get("/api/load/monthly")
def load_monthly(
    month_start_dates: str | None = None, months: int = 6
) -> dict[str, list[dict]]:
    """Load actual vs. target per month.

    Query params:
    - `month_start_dates`: optional comma-separated list of ISO
      first-of-month dates, e.g. `2026-05-01,2026-06-01`. When given,
      exactly these months are returned (in the order given).
    - `months`: when `month_start_dates` is omitted, the number of trailing
      months (ending at the current month) to return. Default 6.
    """
    dates = (
        [d.strip() for d in month_start_dates.split(",") if d.strip()]
        if month_start_dates
        else _trailing_month_starts(months)
    )
    result = []
    for month_start_date in dates:
        row = repo.get_monthly_target(month_start_date)
        result.append(
            {
                "month_start_date": month_start_date,
                "load_actual_total": row["load_actual_total"] if row else None,
                "load_target_total": row["load_target_total"] if row else None,
            }
        )
    return {"months": result}
