import os
from unittest.mock import patch

import sqlalchemy as sa
from click.testing import CliRunner

from apex_coach.cli.main import cli


def _env(db_path):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": "test",
        "DATABASE_URL": f"sqlite:///{db_path}",
    }


def test_init_db_creates_all_tables(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(cli, ["init-db"])

    assert result.exit_code == 0

    engine = sa.create_engine(f"sqlite:///{db_path}")
    table_names = set(sa.inspect(engine).get_table_names())
    assert {
        "activities",
        "daily_metrics",
        "decisions",
        "hr_zones",
        "monthly_targets",
        "oauth_tokens",
        "session_scores",
        "weekly_plans",
    } <= table_names


def test_init_db_is_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    with patch.dict(os.environ, _env(db_path), clear=True):
        first = runner.invoke(cli, ["init-db"])
        second = runner.invoke(cli, ["init-db"])

    assert first.exit_code == 0
    assert second.exit_code == 0
