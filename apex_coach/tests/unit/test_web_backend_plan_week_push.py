"""F19.7 (#123): POST /api/plan/week/push against a fixture DB.

Mirrors test_web_backend_plan_week.py's fixture-DB + reloaded-app-module +
TestClient structure, and test_cli_push_week.py's FakePlanExportAdapter
patching pattern (this endpoint dispatches through the exact same
`_push_week()` helper in apex_coach.cli.main that the `push-week` CLI
command uses — F19.6, #121 — so these tests mock the adapter rather than
re-testing push_session()/RealIntervalsIcuAdapter itself, same as the CLI's
own real-adapter test does).
"""

import importlib
import json
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from apex_coach.db.engine import create_engine
from apex_coach.db.plan_repository import PlanRepository
from apex_coach.db.schema import metadata
from apex_coach.db.token_repository import TokenRepository

ENCRYPTION_KEY = "test"
WEEK_START = "2026-08-03"

GENERATED_STRUCTURE = [
    {
        "day": "Monday",
        "session_type": "HIIT",
        "structure": {
            "type": "intervals",
            "rep_count": 6,
            "work_zone": "zone5",
            "work_hr_bpm": 172,
            "work_min": 3.0,
            "recovery_zone": "zone2",
            "recovery_hr_bpm": 140,
            "recovery_min": 2.0,
            "warmup_cooldown_min": 10.0,
            "total_duration_min": 40.0,
        },
    },
    {
        "day": "Tuesday",
        "session_type": "Zone2_Long",
        "structure": {
            "type": "single_block",
            "zone": "zone2",
            "target_hr_bpm": 140,
            "main_set_min": 60.0,
            "warmup_cooldown_min": 10.0,
            "total_duration_min": 70.0,
        },
    },
]


def _env(db_path):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": ENCRYPTION_KEY,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "WHOOP_CLIENT_ID": "test-client-id",
        "WHOOP_CLIENT_SECRET": "test-client-secret",
    }


def _client_for(db_path):
    with patch.dict(os.environ, _env(db_path), clear=True):
        import web.backend.main as main_module

        importlib.reload(main_module)
    return main_module, TestClient(main_module.app)


class FakePlanExportAdapter:
    """Stand-in for RealIntervalsIcuAdapter's push_session — same trick as
    test_cli_push_week.py's FakePlanExportAdapter."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        return self

    def push_session(self, event_date, structured_session, existing_event_id):
        self.calls.append((structured_session["day"], existing_event_id))
        return existing_event_id or f"fake-event-{event_date}"


def _seed_week(db_path, generated_structure_json=GENERATED_STRUCTURE, pushed_event_ids=None):
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    plan_repo = PlanRepository(engine)
    fields = {
        "week_start_date": WEEK_START,
        "planned_sessions_json": json.dumps(
            [{"day": e["day"], "session_type": e["session_type"]} for e in GENERATED_STRUCTURE]
        ),
    }
    if generated_structure_json is not None:
        fields["generated_structure_json"] = json.dumps(generated_structure_json)
    if pushed_event_ids is not None:
        fields["pushed_event_ids_json"] = json.dumps(pushed_event_ids)
    plan_repo.insert_weekly_plan(**fields)
    return engine, plan_repo


def _set_provider_and_token(engine, provider):
    PlanRepository(engine).insert_athlete_profile(activity_sync_provider=provider)
    if provider == "INTERVALS_ICU":
        TokenRepository(engine, ENCRYPTION_KEY).save_token(
            provider="INTERVALS_ICU",
            access_token="test-key",
            refresh_token="",
            expires_at="",
            scope="",
        )


def test_push_week_pushes_all_sessions_and_persists_event_ids(tmp_path):
    db_path = tmp_path / "test.db"
    engine, plan_repo = _seed_week(db_path)
    _set_provider_and_token(engine, "INTERVALS_ICU")

    fake = FakePlanExportAdapter()
    main_module, client = _client_for(db_path)

    with patch("apex_coach.cli.main.RealIntervalsIcuAdapter", fake):
        response = client.post("/api/plan/week/push", params={"week_start": WEEK_START})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["week_start_date"] == WEEK_START
    assert {d["day"] for d in body["pushed_days"]} == {"Monday", "Tuesday"}
    for entry in body["pushed_days"]:
        assert entry["event_id"]

    week = plan_repo.get_weekly_plan(WEEK_START)
    event_ids = json.loads(week["pushed_event_ids_json"])
    assert set(event_ids) == {"Monday", "Tuesday"}

    # Second push updates in place rather than creating duplicates.
    with patch("apex_coach.cli.main.RealIntervalsIcuAdapter", fake):
        response2 = client.post("/api/plan/week/push", params={"week_start": WEEK_START})
    assert response2.status_code == 200, response2.text

    first_call_ids = {day: existing for day, existing in fake.calls[:2]}
    second_call_ids = {day: existing for day, existing in fake.calls[2:]}
    assert all(existing is None for existing in first_call_ids.values())
    assert all(existing is not None for existing in second_call_ids.values())


def test_push_week_after_get_reflects_pushed_status(tmp_path):
    db_path = tmp_path / "test.db"
    engine, plan_repo = _seed_week(db_path)
    _set_provider_and_token(engine, "INTERVALS_ICU")

    fake = FakePlanExportAdapter()
    _main_module, client = _client_for(db_path)

    get_before = client.get("/api/plan/week", params={"week_start": WEEK_START})
    assert all(day["pushed"] is False for day in get_before.json()["days"])

    with patch("apex_coach.cli.main.RealIntervalsIcuAdapter", fake):
        push_response = client.post("/api/plan/week/push", params={"week_start": WEEK_START})
    assert push_response.status_code == 200, push_response.text

    get_after = client.get("/api/plan/week", params={"week_start": WEEK_START})
    assert all(day["pushed"] is True for day in get_after.json()["days"])


def test_push_week_rejects_strava_provider(tmp_path):
    db_path = tmp_path / "test.db"
    engine, _plan_repo = _seed_week(db_path)
    _set_provider_and_token(engine, "STRAVA")

    _main_module, client = _client_for(db_path)
    response = client.post("/api/plan/week/push", params={"week_start": WEEK_START})

    assert response.status_code == 400, response.text
    assert "only supported for intervals.icu" in response.json()["detail"]


def test_push_week_without_stored_key_gives_clean_error(tmp_path):
    db_path = tmp_path / "test.db"
    engine, _plan_repo = _seed_week(db_path)
    PlanRepository(engine).insert_athlete_profile(activity_sync_provider="INTERVALS_ICU")
    # No token saved.

    _main_module, client = _client_for(db_path)
    response = client.post("/api/plan/week/push", params={"week_start": WEEK_START})

    assert response.status_code == 400, response.text
    assert "connect-intervals-icu" in response.json()["detail"]


def test_push_week_requires_generated_structure(tmp_path):
    db_path = tmp_path / "test.db"
    engine, _plan_repo = _seed_week(db_path, generated_structure_json=None)
    _set_provider_and_token(engine, "INTERVALS_ICU")

    _main_module, client = _client_for(db_path)
    response = client.post("/api/plan/week/push", params={"week_start": WEEK_START})

    assert response.status_code == 400, response.text
    assert "generate-week-structure" in response.json()["detail"]


def test_push_week_no_weekly_plan_row_returns_404(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    _main_module, client = _client_for(db_path)
    response = client.post("/api/plan/week/push", params={"week_start": "2099-01-05"})

    assert response.status_code == 404
    assert "2099-01-05" in response.json()["detail"]


def test_push_week_rejects_invalid_date(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    _main_module, client = _client_for(db_path)
    response = client.post("/api/plan/week/push", params={"week_start": "not-a-date"})

    assert response.status_code == 400
