"""F19.2 (#118): 97b6ef7dddad adds weekly_plans.generated_structure_json.
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


def test_migration_adds_generated_structure_json_column(tmp_path):
    db_path = tmp_path / "migration_test.db"
    cfg = _config(db_path)

    command.upgrade(cfg, "00edfdac9559")
    command.upgrade(cfg, "97b6ef7dddad")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)

    columns = {c["name"] for c in inspector.get_columns("weekly_plans")}
    assert "generated_structure_json" in columns

    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO weekly_plans (id, week_start_date, created_at, generated_structure_json) "
                "VALUES ('week-id', '2026-08-03', '2026-08-01T00:00:00Z', '[{\"day\": \"Monday\"}]')"
            )
        )
        row = conn.execute(
            sa.text("SELECT generated_structure_json FROM weekly_plans WHERE id = 'week-id'")
        ).one()
        assert row.generated_structure_json == '[{"day": "Monday"}]'


def test_migration_downgrade_removes_generated_structure_json_column(tmp_path):
    db_path = tmp_path / "migration_test.db"
    cfg = _config(db_path)

    command.upgrade(cfg, "97b6ef7dddad")
    command.downgrade(cfg, "00edfdac9559")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("weekly_plans")}
    assert "generated_structure_json" not in columns
