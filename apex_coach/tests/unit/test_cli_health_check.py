import json
import os
from unittest.mock import patch

from click.testing import CliRunner

from apex_coach.cli.main import cli
from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository


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


def test_morning_check_hiit_full_sequence_persists_answers(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    # 3 fixed questions + HIIT's 3 adaptive questions (left_knee_pain,
    # right_knee_pain, shin_calf_tightness), one line each, in order.
    answer_input = "3\n2\n4\n1\n2\n3\n"

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli,
            ["morning-check", "--session-type", "HIIT", "--date", "2026-08-01"],
            input=answer_input,
        )

    assert result.exit_code == 0, result.output
    assert "Health check for 2026-08-01 saved." in result.output
    assert "Override triggered" not in result.output

    engine = create_engine(str(db_path))
    repo = MetricsRepository(engine)
    row = repo.get_daily_metrics("2026-08-01")

    assert row is not None
    assert row["muscle_soreness"] == 3
    assert row["subjective_energy"] == 2
    assert row["sleep_quality_felt"] == 4

    health_check_json = json.loads(row["health_check_json"])
    assert health_check_json["session_type"] == "HIIT"
    assert health_check_json["adaptive_answers"]["left_knee_pain"]["score"] == 1
    assert health_check_json["adaptive_answers"]["right_knee_pain"]["score"] == 2
    assert health_check_json["adaptive_answers"]["shin_calf_tightness"]["score"] == 3
    assert health_check_json["override_triggered"] is False
    assert health_check_json["override_reasons"] == []

    # WHOOP-only fields must be untouched by the health check writer.
    assert row["whoop_recovery_pct"] is None


def test_morning_check_zone2_short_single_adaptive_question(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    # 3 fixed questions + Zone2_Short's single adaptive question (leg_fatigue).
    answer_input = "5\n5\n5\n5\n"

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli,
            ["morning-check", "--session-type", "Zone2_Short", "--date", "2026-08-02"],
            input=answer_input,
        )

    assert result.exit_code == 0, result.output

    engine = create_engine(str(db_path))
    repo = MetricsRepository(engine)
    row = repo.get_daily_metrics("2026-08-02")
    assert row is not None
    assert row["muscle_soreness"] == 5

    health_check_json = json.loads(row["health_check_json"])
    assert health_check_json["adaptive_answers"]["leg_fatigue"]["score"] == 5


def test_morning_check_prints_override_reason_when_triggered(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    # Zone2_Short's leg_fatigue >= OVERRIDE_THRESHOLD (4) trips the override.
    answer_input = "2\n2\n2\n4\n"

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli,
            ["morning-check", "--session-type", "Zone2_Short", "--date", "2026-08-03"],
            input=answer_input,
        )

    assert result.exit_code == 0, result.output
    assert "Override triggered" in result.output
    assert "health_check_override: leg_fatigue = 4" in result.output
    assert "override noted above" in result.output

    engine = create_engine(str(db_path))
    repo = MetricsRepository(engine)
    row = repo.get_daily_metrics("2026-08-03")
    health_check_json = json.loads(row["health_check_json"])
    assert health_check_json["override_triggered"] is True
    assert health_check_json["override_reasons"] == ["health_check_override: leg_fatigue = 4"]


def test_morning_check_rejects_out_of_range_answer_then_reprompts(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    # First answer to the first fixed question is out of range (9), then
    # click.IntRange re-prompts; the remaining 6 valid answers complete the
    # HIIT sequence (3 fixed + 3 adaptive).
    answer_input = "9\n3\n2\n4\n1\n2\n3\n"

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli,
            ["morning-check", "--session-type", "HIIT", "--date", "2026-08-04"],
            input=answer_input,
        )

    assert result.exit_code == 0, result.output

    engine = create_engine(str(db_path))
    repo = MetricsRepository(engine)
    row = repo.get_daily_metrics("2026-08-04")
    assert row is not None
    assert row["muscle_soreness"] == 3


def test_morning_check_rejects_unknown_session_type(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli, ["morning-check", "--session-type", "NotARealType"]
        )

    assert result.exit_code != 0
