"""F18.4 (#93): 00edfdac9559 adds athlete_profile.activity_sync_provider and
extends oauth_tokens.provider's CHECK constraint to allow INTERVALS_ICU.
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


def test_migration_adds_column_and_extends_check_constraints(tmp_path):
    db_path = tmp_path / "migration_test.db"
    cfg = _config(db_path)

    command.upgrade(cfg, "aa5ca4244050")
    command.upgrade(cfg, "00edfdac9559")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)

    columns = {c["name"] for c in inspector.get_columns("athlete_profile")}
    assert "activity_sync_provider" in columns

    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO athlete_profile (id, created_at, activity_sync_provider) "
                "VALUES ('test-id', '2026-08-01T00:00:00Z', 'INTERVALS_ICU')"
            )
        )
        row = conn.execute(
            sa.text("SELECT activity_sync_provider FROM athlete_profile WHERE id = 'test-id'")
        ).one()
        assert row.activity_sync_provider == "INTERVALS_ICU"

        conn.execute(
            sa.text(
                "INSERT INTO oauth_tokens (id, provider, updated_at) "
                "VALUES ('token-id', 'INTERVALS_ICU', '2026-08-01T00:00:00Z')"
            )
        )


def test_migration_rejects_unrecognized_activity_sync_provider(tmp_path):
    db_path = tmp_path / "migration_test.db"
    cfg = _config(db_path)

    command.upgrade(cfg, "00edfdac9559")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO athlete_profile (id, created_at, activity_sync_provider) "
                    "VALUES ('bad-id', '2026-08-01T00:00:00Z', 'GARMIN_CONNECT')"
                )
            )
            raised = False
        except sa.exc.IntegrityError:
            raised = True
    assert raised


def test_migration_downgrade_removes_column_and_reverts_constraint(tmp_path):
    db_path = tmp_path / "migration_test.db"
    cfg = _config(db_path)

    command.upgrade(cfg, "00edfdac9559")
    command.downgrade(cfg, "aa5ca4244050")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("athlete_profile")}
    assert "activity_sync_provider" not in columns

    with engine.begin() as conn:
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO oauth_tokens (id, provider, updated_at) "
                    "VALUES ('token-id', 'INTERVALS_ICU', '2026-08-01T00:00:00Z')"
                )
            )
            raised = False
        except sa.exc.IntegrityError:
            raised = True
    assert raised  # INTERVALS_ICU no longer a valid oauth_tokens.provider value
