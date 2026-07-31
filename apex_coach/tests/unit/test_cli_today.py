from click.testing import CliRunner

from apex_coach.cli.main import cli


def _invoke(runner, **overrides):
    args = {
        "--session-type": "HIIT",
        "--recovery-band": "RECOVERY_GREEN",
        "--hrv-signal": "HRV_POSITIVE",
        "--soreness-band": "SORENESS_NONE",
    }
    args.update(overrides)
    flat = []
    for k, v in args.items():
        flat += [k, v]
    return runner.invoke(cli, ["today"] + flat)


def test_today_prints_recommendation_and_rationale():
    runner = CliRunner()
    result = _invoke(runner)

    assert result.exit_code == 0
    assert "Recommendation: GO" in result.output
    assert "Rationale:" in result.output


def test_today_prints_recovery_week_flag_when_red():
    runner = CliRunner()
    result = _invoke(runner, **{"--recovery-band": "RECOVERY_RED"})

    assert result.exit_code == 0
    assert "Recommendation: ABORT" in result.output
    assert "check_recovery_week_trigger" in result.output


def test_today_override_flag_forces_abort():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "today",
            "--session-type",
            "HIIT",
            "--recovery-band",
            "RECOVERY_GREEN",
            "--hrv-signal",
            "HRV_POSITIVE",
            "--soreness-band",
            "SORENESS_NONE",
            "--override",
        ],
    )

    assert result.exit_code == 0
    assert "Recommendation: ABORT" in result.output


def test_today_rejects_invalid_recovery_band():
    runner = CliRunner()
    result = _invoke(runner, **{"--recovery-band": "not-a-band"})

    assert result.exit_code != 0
