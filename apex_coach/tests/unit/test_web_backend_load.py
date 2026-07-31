import importlib
import os
import sys
from datetime import date, timedelta
from unittest.mock import patch

from click.testing import CliRunner
from fastapi.testclient import TestClient

from apex_coach.cli.main import cli
from apex_coach.db.engine import create_engine
from apex_coach.db.plan_repository import PlanRepository


def _env(db_path):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": "test",
        "DATABASE_URL": f"sqlite:///{db_path}",
    }


def _init_db(runner, db_path):
    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(cli, ["init-db"])
    assert result.exit_code == 0, result.output


def _client_for(db_path) -> TestClient:
    """(Re-)import web.backend.main against `db_path`.

    main.py builds its DB engine/repo once at import time from the
    DATABASE_URL env var (F16.1 pattern), so each test that wants an
    isolated DB re-imports the module fresh under a patched environment.
    """
    sys.modules.pop("web.backend.main", None)
    with patch.dict(os.environ, _env(db_path), clear=True):
        module = importlib.import_module("web.backend.main")
    return TestClient(module.app)


def test_load_weekly_returns_actual_and_target_for_requested_weeks(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    engine = create_engine(str(db_path))
    plan_repo = PlanRepository(engine)
    plan_repo.insert_weekly_plan(
        week_start_date="2026-07-06", load_actual=310.5, load_target=350.0
    )
    plan_repo.insert_weekly_plan(
        week_start_date="2026-07-13", load_actual=330.0, load_target=350.0
    )

    client = _client_for(db_path)
    response = client.get(
        "/api/load/weekly",
        params={"week_start_dates": "2026-07-06,2026-07-13,2026-07-20"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "weeks": [
            {
                "week_start_date": "2026-07-06",
                "load_actual": 310.5,
                "load_target": 350.0,
            },
            {
                "week_start_date": "2026-07-13",
                "load_actual": 330.0,
                "load_target": 350.0,
            },
            {
                "week_start_date": "2026-07-20",
                "load_actual": None,
                "load_target": None,
            },
        ]
    }


def test_load_weekly_defaults_to_trailing_weeks_ending_at_current_week(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    client = _client_for(db_path)
    response = client.get("/api/load/weekly", params={"weeks": 3})

    assert response.status_code == 200
    weeks = response.json()["weeks"]
    assert len(weeks) == 3

    current_monday = date.today() - timedelta(days=date.today().weekday())
    expected_dates = [
        (current_monday - timedelta(weeks=offset)).isoformat() for offset in (2, 1, 0)
    ]
    assert [w["week_start_date"] for w in weeks] == expected_dates
    # No seeded rows for these weeks -> nulls, not an error/omission.
    assert all(w["load_actual"] is None and w["load_target"] is None for w in weeks)


def test_load_monthly_returns_actual_and_target_for_requested_months(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    engine = create_engine(str(db_path))
    plan_repo = PlanRepository(engine)
    plan_repo.insert_monthly_target(
        month_start_date="2026-06-01",
        load_actual_total=1200.0,
        load_target_total=1400.0,
    )

    client = _client_for(db_path)
    response = client.get(
        "/api/load/monthly",
        params={"month_start_dates": "2026-06-01,2026-07-01"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "months": [
            {
                "month_start_date": "2026-06-01",
                "load_actual_total": 1200.0,
                "load_target_total": 1400.0,
            },
            {
                "month_start_date": "2026-07-01",
                "load_actual_total": None,
                "load_target_total": None,
            },
        ]
    }


def test_load_monthly_defaults_to_trailing_months_ending_at_current_month(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    client = _client_for(db_path)
    response = client.get("/api/load/monthly", params={"months": 2})

    assert response.status_code == 200
    months = response.json()["months"]
    assert len(months) == 2

    today = date.today()
    current_month_start = date(today.year, today.month, 1)
    prev_month_index = today.month - 2  # 0-based
    prev_year = today.year + prev_month_index // 12
    prev_month = prev_month_index % 12 + 1
    expected_dates = [
        date(prev_year, prev_month, 1).isoformat(),
        current_month_start.isoformat(),
    ]
    assert [m["month_start_date"] for m in months] == expected_dates
