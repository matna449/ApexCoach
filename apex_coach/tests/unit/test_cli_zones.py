from click.testing import CliRunner

from apex_coach.cli.main import cli


def test_zones_command_prints_all_5_zones():
    runner = CliRunner()
    result = runner.invoke(cli, ["zones", "--max-hr", "192", "--resting-hr", "48"])

    assert result.exit_code == 0
    assert "Zone 1 (Recovery): 120-134 bpm" in result.output
    assert "Zone 2 (Aerobic base): 134-149 bpm" in result.output
    assert "Zone 3 (Tempo): 149-163 bpm" in result.output
    assert "Zone 4 (Threshold): 163-178 bpm" in result.output
    assert "Zone 5 (VO2max): 178-192 bpm" in result.output


def test_zones_command_requires_both_flags():
    runner = CliRunner()
    result = runner.invoke(cli, ["zones", "--max-hr", "192"])

    assert result.exit_code != 0
    assert "resting-hr" in result.output.lower()


def test_zones_command_propagates_validation_error():
    runner = CliRunner()
    result = runner.invoke(cli, ["zones", "--max-hr", "150", "--resting-hr", "150"])

    assert result.exit_code != 0
