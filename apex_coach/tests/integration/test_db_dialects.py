import os
import subprocess
import sys
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from click.testing import CliRunner
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateIndex

from apex_coach.cli.main import cli
from apex_coach.config.settings import normalize_database_url
from apex_coach.db.engine import create_engine
from apex_coach.db.schema import daily_metrics, metadata, race_goals
from apex_coach.db.token_repository import TokenRepository
from apex_coach.db.upsert import dialect_insert

POSTGRES_URL = "postgresql+psycopg://user:secret@db.example.com/apex?sslmode=require"


@pytest.mark.parametrize(
    "url",
    [
        "postgres://user:secret@db.example.com/apex?sslmode=require",
        "postgresql://user:secret@db.example.com/apex?sslmode=require",
        POSTGRES_URL,
    ],
)
def test_postgres_urls_are_normalized_to_the_psycopg_driver(url):
    assert normalize_database_url(url) == POSTGRES_URL


def test_sqlite_urls_are_left_alone():
    assert normalize_database_url("sqlite:///./apex_coach.db") == "sqlite:///./apex_coach.db"


def test_create_engine_accepts_a_sqlite_url_and_enforces_foreign_keys(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    metadata.create_all(engine)

    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(metadata.tables["hr_zones"].insert().values(date="2026-07-30"))


def test_create_engine_builds_a_small_postgres_pool_without_connecting():
    engine = create_engine(POSTGRES_URL)

    assert engine.dialect.name == "postgresql"
    assert engine.pool.size() == 2
    assert engine.pool._pre_ping is True


@pytest.mark.parametrize(
    ("dialect_name", "dialect"),
    [("sqlite", sqlite.dialect()), ("postgresql", postgresql.dialect())],
)
def test_upsert_compiles_for_each_dialect(dialect_name, dialect):
    engine = sa.create_mock_engine(f"{dialect_name}://", executor=None)
    stmt = dialect_insert(engine, daily_metrics).values(date="2026-07-30", whoop_hrv_ms=55.0)
    stmt = stmt.on_conflict_do_update(
        index_elements=[daily_metrics.c.date],
        set_={"whoop_hrv_ms": stmt.excluded.whoop_hrv_ms},
    )

    sql = str(stmt.compile(dialect=dialect))

    assert "ON CONFLICT (date) DO UPDATE SET whoop_hrv_ms = excluded.whoop_hrv_ms" in sql


def test_one_active_race_goal_index_is_partial_on_postgres():
    index = next(i for i in race_goals.indexes if i.name == "ix_race_goals_one_active")

    sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))

    assert "WHERE status = 'ACTIVE'" in sql


def test_init_db_never_prints_the_database_password(monkeypatch):
    monkeypatch.setenv("APEX_ENCRYPTION_KEY", "test-key")
    monkeypatch.setenv("DATABASE_URL", POSTGRES_URL)

    with patch("apex_coach.cli.main.metadata.create_all"):
        result = CliRunner().invoke(cli, ["init-db"])

    assert result.exit_code == 0, result.output
    assert "db.example.com" in result.output
    assert "secret" not in result.output


def _alembic_config(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _table_names(url: str) -> set[str]:
    engine = sa.create_engine(url)
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migrations_round_trip_on_sqlite(tmp_path):
    cfg = _alembic_config(f"sqlite:///{tmp_path / 'round_trip.db'}")

    command.upgrade(cfg, "head")
    assert set(metadata.tables) <= _table_names(f"sqlite:///{tmp_path / 'round_trip.db'}")

    command.downgrade(cfg, "base")
    assert _table_names(f"sqlite:///{tmp_path / 'round_trip.db'}") == {"alembic_version"}


def test_programmatic_alembic_ignores_database_url(tmp_path, monkeypatch):
    target = tmp_path / "target.db"
    other = tmp_path / "other.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{other}")

    command.upgrade(_alembic_config(f"sqlite:///{target}"), "head")

    assert "race_goals" in _table_names(f"sqlite:///{target}")
    assert not other.exists()


def test_alembic_command_uses_database_url(tmp_path):
    db_path = tmp_path / "from_env.db"

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db_path}"},
    )

    assert "race_goals" in _table_names(f"sqlite:///{db_path}")


def _insert_race_goal(conn, id_, status):
    conn.execute(
        race_goals.insert().values(
            id=id_, goal_distance="10K", target_race_date="2027-05-01", status=status
        )
    )


def _assert_one_active_only(engine):
    with engine.begin() as conn:
        _insert_race_goal(conn, "a", "COMPLETED")
        _insert_race_goal(conn, "b", "COMPLETED")
        _insert_race_goal(conn, "c", "ABANDONED")
        _insert_race_goal(conn, "d", "ACTIVE")
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            _insert_race_goal(conn, "e", "ACTIVE")


@pytest.mark.postgres
def test_race_goal_index_allows_many_finished_rows_and_one_active(repository_engine):
    _assert_one_active_only(repository_engine)


@pytest.fixture
def empty_postgres(postgres_url):
    engine = create_engine(postgres_url)

    def reset():
        with engine.begin() as conn:
            conn.execute(sa.text("DROP SCHEMA public CASCADE"))
            conn.execute(sa.text("CREATE SCHEMA public"))

    reset()
    yield engine
    reset()
    engine.dispose()


@pytest.mark.postgres
def test_migrations_round_trip_on_postgres(empty_postgres, postgres_url):
    cfg = _alembic_config(postgres_url)

    command.upgrade(cfg, "head")
    assert set(metadata.tables) <= set(sa.inspect(empty_postgres).get_table_names())
    _assert_one_active_only(empty_postgres)

    command.downgrade(cfg, "base")
    assert set(sa.inspect(empty_postgres).get_table_names()) == {"alembic_version"}


@pytest.mark.postgres
def test_migrated_postgres_stores_an_intervals_icu_token(empty_postgres, postgres_url):
    command.upgrade(_alembic_config(postgres_url), "head")
    repo = TokenRepository(empty_postgres, "test-key")

    repo.save_token("INTERVALS_ICU", "api-key", "", "2099-01-01T00:00:00+00:00", "")

    assert repo.get_token("INTERVALS_ICU")["access_token"] == "api-key"


@pytest.mark.postgres
def test_migrated_postgres_schema_matches_schema_py(empty_postgres, postgres_url):
    command.upgrade(_alembic_config(postgres_url), "head")

    with empty_postgres.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), metadata)

    assert diff == []
