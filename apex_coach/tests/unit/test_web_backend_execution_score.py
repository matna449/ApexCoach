"""Unit tests for the F16.4 execution-score-trend endpoint
(`GET /api/execution-score-trend` in web/backend/main.py) — FastAPI's
TestClient against a temp SQLite DB, seeded via MetricsRepository directly,
following this repo's `APEX_ENCRYPTION_KEY`/`DATABASE_URL` env-var pattern
(see apex_coach/tests/unit/test_cli_sync_session.py).
"""

import importlib
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository

ENCRYPTION_KEY = "test-passphrase-not-for-production"


def _env(db_path):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": ENCRYPTION_KEY,
        "DATABASE_URL": f"sqlite:///{db_path}",
    }


def _make_client(db_path):
    """web/backend/main.py builds its engine/repo at import time from
    get_settings(), so the env vars must be set before the module is
    imported (or re-imported, if a previous test already imported it)."""
    import web.backend.main as main_module

    with patch.dict(os.environ, _env(db_path), clear=True):
        importlib.reload(main_module)
    return TestClient(main_module.app), main_module


def _seed(db_path):
    from apex_coach.db.schema import metadata

    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    repo = MetricsRepository(engine)

    for date, strava_id, score, overpush, underpush in [
        ("2026-07-01", "1001", 85.0, False, False),
        ("2026-07-10", "1002", 40.0, False, True),
        ("2026-07-20", "1003", 95.0, True, False),
    ]:
        repo.insert_daily_metrics(date=date)
        repo.save_activity(
            strava_id=strava_id,
            date=date,
            activity_type="Run",
            intended_session_type="Zone2_Short",
        )
        activity = repo.get_activity(strava_id)
        repo.insert_session_score(
            activity_id=activity["id"],
            execution_score=score,
            overpush_flag=overpush,
            underpush_flag=underpush,
        )

    # An activity with no session_scores row — must be excluded from points.
    repo.insert_daily_metrics(date="2026-07-25")
    repo.save_activity(
        strava_id="1004",
        date="2026-07-25",
        activity_type="Run",
        intended_session_type="Zone2_Short",
    )

    return repo


def test_execution_score_trend_returns_points_and_flag_counts(tmp_path):
    db_path = tmp_path / "test.db"
    _seed(db_path)
    client, _ = _make_client(db_path)

    response = client.get(
        "/api/execution-score-trend",
        params={"start_date": "2026-07-01", "end_date": "2026-07-31"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["start_date"] == "2026-07-01"
    assert body["end_date"] == "2026-07-31"
    assert len(body["points"]) == 3  # the 4th activity has no session_scores row
    assert [p["execution_score"] for p in body["points"]] == [85.0, 40.0, 95.0]
    assert [p["date"] for p in body["points"]] == ["2026-07-01", "2026-07-10", "2026-07-20"]
    assert body["overpush_count"] == 1
    assert body["underpush_count"] == 1


def test_execution_score_trend_filters_by_date_range(tmp_path):
    db_path = tmp_path / "test.db"
    _seed(db_path)
    client, _ = _make_client(db_path)

    response = client.get(
        "/api/execution-score-trend",
        params={"start_date": "2026-07-05", "end_date": "2026-07-15"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["points"]) == 1
    assert body["points"][0]["date"] == "2026-07-10"
    assert body["overpush_count"] == 0
    assert body["underpush_count"] == 1


def test_execution_score_trend_empty_range_returns_zero_counts(tmp_path):
    db_path = tmp_path / "test.db"
    _seed(db_path)
    client, _ = _make_client(db_path)

    response = client.get(
        "/api/execution-score-trend",
        params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["points"] == []
    assert body["overpush_count"] == 0
    assert body["underpush_count"] == 0
