"""F16.2 (#68): GET /api/trends/hrv against a fixture DB.

`web/backend/main.py` builds its `engine`/`repo` at module import time from
`DATABASE_URL`/`APEX_ENCRYPTION_KEY`, exactly like the CLI's `init-db`
command. So each test sets those env vars to a `tmp_path` SQLite file
(matching `apex_coach/tests/unit/test_cli_athlete_profile.py`'s pattern)
*before* importing/reloading `web.backend.main`, seeds real `daily_metrics`
rows via `MetricsRepository` against that same file, then drives the
endpoint with FastAPI's `TestClient`.
"""

import importlib
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.schema import metadata


def _env(db_path):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": "test",
        "DATABASE_URL": f"sqlite:///{db_path}",
    }


def _client_for(db_path):
    """Reload web.backend.main under the given DATABASE_URL so its
    module-level engine/repo point at this test's fixture DB, and return a
    TestClient bound to that fresh app instance."""
    with patch.dict(os.environ, _env(db_path), clear=True):
        import web.backend.main as main_module

        importlib.reload(main_module)
    return TestClient(main_module.app)


def test_hrv_trend_returns_seeded_readings_in_range(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    repo = MetricsRepository(engine)
    repo.insert_daily_metrics(date="2024-01-01", whoop_hrv_ms=55.0)
    repo.insert_daily_metrics(date="2024-01-02", whoop_hrv_ms=None)
    repo.insert_daily_metrics(date="2024-01-03", whoop_hrv_ms=62.5)
    # Outside the requested range — must not appear in the response.
    repo.insert_daily_metrics(date="2024-02-01", whoop_hrv_ms=70.0)

    client = _client_for(db_path)
    response = client.get("/api/trends/hrv?start=2024-01-01&end=2024-01-03")

    assert response.status_code == 200
    assert response.json() == [
        {"date": "2024-01-01", "whoop_hrv_ms": 55.0},
        {"date": "2024-01-02", "whoop_hrv_ms": None},
        {"date": "2024-01-03", "whoop_hrv_ms": 62.5},
    ]


def test_hrv_trend_empty_range_returns_empty_list(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    repo = MetricsRepository(engine)
    repo.insert_daily_metrics(date="2024-01-01", whoop_hrv_ms=55.0)

    client = _client_for(db_path)
    response = client.get("/api/trends/hrv?start=2025-01-01&end=2025-01-31")

    assert response.status_code == 200
    assert response.json() == []


def test_hrv_trend_defaults_to_trailing_30_days_when_no_params_given(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    repo = MetricsRepository(engine)

    from datetime import date

    today = date.today().isoformat()
    repo.insert_daily_metrics(date=today, whoop_hrv_ms=48.0)

    client = _client_for(db_path)
    response = client.get("/api/trends/hrv")

    assert response.status_code == 200
    assert response.json() == [{"date": today, "whoop_hrv_ms": 48.0}]
