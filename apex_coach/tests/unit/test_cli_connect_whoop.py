import os
from unittest.mock import patch

from click.testing import CliRunner

from apex_coach.cli.main import cli


def test_whoop_smoke_mock_path_unaffected_by_real_flag_absence():
    runner = CliRunner()
    result = runner.invoke(cli, ["whoop-smoke", "--date", "2026-07-30"])

    assert result.exit_code == 0
    assert "Recovery: 62.0%" in result.output


def test_whoop_smoke_real_without_credentials_gives_clean_error(tmp_path):
    runner = CliRunner()
    env = {**os.environ, "APEX_ENCRYPTION_KEY": "test", "WHOOP_CLIENT_ID": "", "WHOOP_CLIENT_SECRET": ""}
    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["whoop-smoke", "--real"])

    assert result.exit_code != 0
    assert "WHOOP_CLIENT_ID" in result.output


def test_connect_whoop_without_credentials_gives_clean_error():
    runner = CliRunner()
    env = {**os.environ, "APEX_ENCRYPTION_KEY": "test", "WHOOP_CLIENT_ID": "", "WHOOP_CLIENT_SECRET": ""}
    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["connect-whoop"])

    assert result.exit_code != 0
    assert "developer.whoop.com" in result.output
