"""F19.8 (#137): GET/POST /api/plan/month/target against a fixture DB.

Mirrors test_web_backend_plan_month.py's structure (fixture-DB engine +
reloaded app module + TestClient). Both endpoints wrap the exact same
persistence path the CLI's `set-monthly-target` command uses --
PlanRepository.get_monthly_target() for reads, and the shared
`_upsert_monthly_target()` helper (apex_coach.cli.main, extracted alongside
this ticket) for writes -- so these tests exercise the HTTP layer, not a
second copy of the insert-vs-update-by-existence branching (already covered
by test_cli_monthly_target.py).
"""

import importlib
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from apex_coach.db.engine import create_engine
from apex_coach.db.plan_repository import PlanRepository
from apex_coach.db.schema import metadata


def _env(db_path):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": "test",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "WHOOP_CLIENT_ID": "test-client-id",
        "WHOOP_CLIENT_SECRET": "test-client-secret",
    }


def _client_for(db_path):
    with patch.dict(os.environ, _env(db_path), clear=True):
        import web.backend.main as main_module

        importlib.reload(main_module)
    return main_module, TestClient(main_module.app)


def test_get_monthly_target_with_no_stored_row(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    _main_module, client = _client_for(db_path)
    response = client.get("/api/plan/month/target", params={"month_start": "2026-08-01"})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "month_start_date": "2026-08-01",
        "exists": False,
        "periodisation_phase": None,
        "load_target_total": None,
        "race_date": None,
    }


def test_get_monthly_target_rejects_invalid_date(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    _main_module, client = _client_for(db_path)
    response = client.get("/api/plan/month/target", params={"month_start": "not-a-date"})

    assert response.status_code == 400


def test_post_monthly_target_creates_a_new_row(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    _main_module, client = _client_for(db_path)
    response = client.post(
        "/api/plan/month/target",
        params={"month_start": "2026-08-01"},
        json={
            "periodisation_phase": "BUILD",
            "load_target_total": 450,
            "race_date": "2026-09-15",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["month_start_date"] == "2026-08-01"
    assert body["created"] is True
    assert body["periodisation_phase"] == "BUILD"
    assert body["load_target_total"] == 450
    assert body["race_date"] == "2026-09-15"

    get_response = client.get("/api/plan/month/target", params={"month_start": "2026-08-01"})
    assert get_response.json() == {
        "month_start_date": "2026-08-01",
        "exists": True,
        "periodisation_phase": "BUILD",
        "load_target_total": 450,
        "race_date": "2026-09-15",
    }


def test_post_monthly_target_updates_an_existing_row(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    plan_repo = PlanRepository(engine)
    plan_repo.insert_monthly_target(
        month_start_date="2026-08-01",
        periodisation_phase="BASE",
        load_target_total=300,
        race_date=None,
    )

    _main_module, client = _client_for(db_path)
    response = client.post(
        "/api/plan/month/target",
        params={"month_start": "2026-08-01"},
        json={"periodisation_phase": "BUILD", "load_target_total": 400},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] is False
    assert body["periodisation_phase"] == "BUILD"
    assert body["load_target_total"] == 400
    assert body["race_date"] is None


def test_post_monthly_target_omits_race_date_defaults_to_none(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    _main_module, client = _client_for(db_path)
    response = client.post(
        "/api/plan/month/target",
        params={"month_start": "2026-08-01"},
        json={"periodisation_phase": "BASE", "load_target_total": 300},
    )

    assert response.status_code == 200, response.text
    assert response.json()["race_date"] is None


def test_post_monthly_target_rejects_unknown_periodisation_phase(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    _main_module, client = _client_for(db_path)
    response = client.post(
        "/api/plan/month/target",
        params={"month_start": "2026-08-01"},
        json={"periodisation_phase": "NOT_A_PHASE", "load_target_total": 300},
    )

    assert response.status_code == 400


def test_post_monthly_target_rejects_invalid_month_start(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    _main_module, client = _client_for(db_path)
    response = client.post(
        "/api/plan/month/target",
        params={"month_start": "not-a-date"},
        json={"periodisation_phase": "BASE", "load_target_total": 300},
    )

    assert response.status_code == 400


def test_post_monthly_target_rejects_invalid_race_date(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    _main_module, client = _client_for(db_path)
    response = client.post(
        "/api/plan/month/target",
        params={"month_start": "2026-08-01"},
        json={
            "periodisation_phase": "BASE",
            "load_target_total": 300,
            "race_date": "not-a-date",
        },
    )

    assert response.status_code == 400
