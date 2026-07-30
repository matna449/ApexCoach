from click.testing import CliRunner

from apex_coach.cli.main import cli


def test_strava_smoke_prints_activity_fields():
    runner = CliRunner()
    result = runner.invoke(cli, ["strava-smoke"])

    assert result.exit_code == 0
    assert "Tuesday Threshold - Track Session (Run)" in result.output
    assert "Distance: 9843.2 m" in result.output
    assert "Duration: 3247 s" in result.output
    assert "Avg HR: 161.4 bpm" in result.output
    assert "Pace:" in result.output
    assert "Elevation gain: 84.0 m" in result.output


def test_strava_smoke_since_ts_before_activity_prints_it():
    runner = CliRunner()
    result = runner.invoke(cli, ["strava-smoke", "--since-ts", "1750000000"])

    assert result.exit_code == 0
    assert "Tuesday Threshold - Track Session (Run)" in result.output


def test_strava_smoke_since_ts_after_activity_prints_nothing():
    runner = CliRunner()
    result = runner.invoke(cli, ["strava-smoke", "--since-ts", "9999999999"])

    assert result.exit_code == 0
    assert result.output == ""
