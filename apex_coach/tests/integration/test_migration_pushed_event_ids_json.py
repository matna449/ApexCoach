"""F19.6 (#121): 5639dfbdf36a adds weekly_plans.pushed_event_ids_json.
Runs against an isolated temp DB via a programmatic alembic Config — never
against alembic.ini's real apex_coach.db (its sqlalchemy.url is hardcoded,
not env-driven).
"""

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

REPO_ROOT_ALEMBIC_INI = "alembic.ini"


def _config(db_path) -> Config:
    cfg = Config(REPO_ROOT_ALEMBIC_INI)
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def test_migration_adds_pushed_event_ids_json_column(tmp_path):
    db_path = tmp_path / "migration_test.db"
    cfg = _config(db_path)

    command.upgrade(cfg, "97b6ef7dddad")
    command.upgrade(cfg, "5639dfbdf36a")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)

    columns = {c["name"] for c in inspector.get_columns("weekly_plans")}
    assert "pushed_event_ids_json" in columns

    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO weekly_plans (id, week_start_date, created_at, pushed_event_ids_json) "
                "VALUES ('week-id', '2026-08-03', '2026-08-01T00:00:00Z', '{\"Monday\": \"555\"}')"
            )
        )
        row = conn.execute(
            sa.text("SELECT pushed_event_ids_json FROM weekly_plans WHERE id = 'week-id'")
        ).one()
        assert row.pushed_event_ids_json == '{"Monday": "555"}'


def test_migration_downgrade_removes_pushed_event_ids_json_column(tmp_path):
    db_path = tmp_path / "migration_test.db"
    cfg = _config(db_path)

    command.upgrade(cfg, "5639dfbdf36a")
    command.downgrade(cfg, "97b6ef7dddad")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("weekly_plans")}
    assert "pushed_event_ids_json" not in columns
