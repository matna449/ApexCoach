import os
from unittest.mock import patch

from click.testing import CliRunner

from apex_coach.cli.main import cli
from apex_coach.db.engine import create_engine
from apex_coach.db.token_repository import TokenRepository


def _env(db_path):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": "test",
        "DATABASE_URL": f"sqlite:///{db_path}",
    }


def _init_db(runner, db_path):
    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(cli, ["init-db"])
    assert result.exit_code == 0


def test_connect_intervals_icu_stores_api_key_via_flag(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli, ["connect-intervals-icu", "--api-key", "test-intervals-icu-key"]
        )

    assert result.exit_code == 0, result.output
    assert "intervals.icu connected" in result.output

    engine = create_engine(str(db_path))
    token = TokenRepository(engine, "test").get_token("INTERVALS_ICU")
    assert token is not None
    assert token["access_token"] == "test-intervals-icu-key"


def test_connect_intervals_icu_prompts_when_flag_omitted(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(cli, ["connect-intervals-icu"], input="prompted-key\n")

    assert result.exit_code == 0, result.output

    engine = create_engine(str(db_path))
    token = TokenRepository(engine, "test").get_token("INTERVALS_ICU")
    assert token["access_token"] == "prompted-key"
