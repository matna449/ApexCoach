from click.testing import CliRunner

from apex_coach.cli.main import cli


def test_whoop_smoke_prints_recovery_hrv_rhr_strain():
    runner = CliRunner()
    result = runner.invoke(cli, ["whoop-smoke", "--date", "2026-07-30"])

    assert result.exit_code == 0
    assert "Recovery: 62.0%" in result.output
    assert "HRV: 71.4 ms" in result.output
    assert "RHR: 48.0 bpm" in result.output
    assert "Strain: 8.4" in result.output


def test_whoop_smoke_defaults_date_to_today():
    runner = CliRunner()
    result = runner.invoke(cli, ["whoop-smoke"])

    assert result.exit_code == 0
    assert "Recovery:" in result.output
