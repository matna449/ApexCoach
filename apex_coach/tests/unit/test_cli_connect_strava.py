import os
from unittest.mock import patch

from click.testing import CliRunner

from apex_coach.cli.main import cli


def test_strava_smoke_real_without_credentials_gives_clean_error():
    runner = CliRunner()
    env = {**os.environ, "APEX_ENCRYPTION_KEY": "test", "STRAVA_CLIENT_ID": "", "STRAVA_CLIENT_SECRET": ""}
    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["strava-smoke", "--real"])

    assert result.exit_code != 0
    assert "STRAVA_CLIENT_ID" in result.output


def test_connect_strava_without_credentials_gives_clean_error():
    runner = CliRunner()
    env = {**os.environ, "APEX_ENCRYPTION_KEY": "test", "STRAVA_CLIENT_ID": "", "STRAVA_CLIENT_SECRET": ""}
    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["connect-strava"])

    assert result.exit_code != 0
    assert "strava.com/settings/api" in result.output
