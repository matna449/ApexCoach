"""F19.5 (#120): GET /api/plan/month against a fixture DB.

Mirrors test_web_backend_plan_week.py's structure (fixture-DB engine +
reloaded app module + TestClient). The endpoint stitches together every
weekly_plans row whose week overlaps the given calendar month, reusing the
exact same per-day payload shape GET /api/plan/week already returns (both
endpoints share `_structured_days()` in web/backend/main.py) -- so these
tests seed generated_structure_json directly, same as F19.4's tests, rather
than re-running the generator.
"""

import importlib
import json
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


MONDAY_STRUCTURE = [
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
]


def test_plan_month_stitches_every_week_overlapping_the_month(tmp_path):
    # August 2026 (a Saturday-starting month) is covered by 6 Mondays:
    # 2026-07-27, 08-03, 08-10, 08-17, 08-24, 08-31 -- the first bleeds in
    # from July, the last bleeds out into September.
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)
    plan_repo = PlanRepository(engine)

    generated_week_starts = ["2026-07-27", "2026-08-10"]
    for week_start in generated_week_starts:
        plan_repo.insert_weekly_plan(
            week_start_date=week_start,
            planned_sessions_json=json.dumps(
                [{"day": e["day"], "session_type": e["session_type"]} for e in MONDAY_STRUCTURE]
            ),
            generated_structure_json=json.dumps(MONDAY_STRUCTURE),
        )
    # A week with a row but no generated structure yet -- should read the
    # same as a week with no row at all, not error.
    plan_repo.insert_weekly_plan(
        week_start_date="2026-08-17",
        planned_sessions_json=json.dumps([{"day": "Monday", "session_type": "HIIT"}]),
    )

    _main_module, client = _client_for(db_path)
    response = client.get("/api/plan/month", params={"month": "2026-08"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["month"] == "2026-08"

    expected_week_starts = [
        "2026-07-27",
        "2026-08-03",
        "2026-08-10",
        "2026-08-17",
        "2026-08-24",
        "2026-08-31",
    ]
    assert [w["week_start_date"] for w in body["weeks"]] == expected_week_starts

    by_start = {w["week_start_date"]: w for w in body["weeks"]}

    for week_start in generated_week_starts:
        week = by_start[week_start]
        assert week["generated"] is True
        assert len(week["days"]) == 1
        assert week["days"][0]["day"] == "Monday"
        assert week["days"][0]["session_type"] == "HIIT"
        assert week["days"][0]["structure"] == MONDAY_STRUCTURE[0]["structure"]
        assert week["days"][0]["pushed"] is False

    # Row exists but ungenerated, and no row at all -- both render the same
    # "nothing generated" shape, no 404 for either (a month is expected to
    # have some weeks unplanned).
    for week_start in ["2026-08-17", "2026-08-03", "2026-08-24", "2026-08-31"]:
        assert by_start[week_start] == {
            "week_start_date": week_start,
            "generated": False,
            "days": [],
        }


def test_plan_month_no_rows_at_all_returns_all_weeks_ungenerated(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    _main_module, client = _client_for(db_path)
    response = client.get("/api/plan/month", params={"month": "2026-08"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["month"] == "2026-08"
    assert len(body["weeks"]) == 6
    assert all(w["generated"] is False and w["days"] == [] for w in body["weeks"])


def test_plan_month_rejects_invalid_month(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    _main_module, client = _client_for(db_path)
    response = client.get("/api/plan/month", params={"month": "not-a-month"})

    assert response.status_code == 400


def test_plan_month_december_rolls_into_next_year(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(str(db_path))
    metadata.create_all(engine)

    _main_module, client = _client_for(db_path)
    response = client.get("/api/plan/month", params={"month": "2026-12"})

    assert response.status_code == 200, response.text
    body = response.json()
    week_starts = [w["week_start_date"] for w in body["weeks"]]
    # 2026-12-31 is a Thursday, so the last overlapping week starts
    # 2026-12-28 and bleeds into January 2027 -- exercises the December ->
    # next-year month-boundary arithmetic.
    assert week_starts[0] == "2026-11-30"
    assert week_starts[-1] == "2026-12-28"
