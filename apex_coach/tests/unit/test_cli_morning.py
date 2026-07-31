import json
import os
from unittest.mock import patch

import sqlalchemy as sa
from click.testing import CliRunner

from apex_coach.adapters.ollama_adapter import ExplanationResult
from apex_coach.adapters.whoop_adapter import MockWhoopAdapter
from apex_coach.cli.main import cli
from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository
from apex_coach.db.plan_repository import PlanRepository
from apex_coach.db.schema import decisions


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


def _plan_week(runner, db_path, **days):
    args = ["plan-week", "--week-start", days.pop("week_start")]
    for day, session_type in days.items():
        args += [f"--{day}", session_type]
    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(cli, args)
    assert result.exit_code == 0, result.output


def _decisions_for(db_path, date):
    engine = create_engine(str(db_path))
    with engine.begin() as conn:
        rows = conn.execute(
            sa.select(decisions)
            .where(decisions.c.date == date)
            .order_by(decisions.c.created_at)
        ).all()
    return [dict(r._mapping) for r in rows]


# HIIT's 3 fixed + 3 adaptive (left_knee_pain, right_knee_pain,
# shin_calf_tightness) questions, all low scores — no override.
_HIIT_NO_OVERRIDE = "3\n2\n4\n1\n2\n2\n"


def test_morning_full_chain_persists_and_prints_recommendation(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)
    _plan_week(
        runner,
        db_path,
        week_start="2026-08-03",
        monday="HIIT",
        tuesday="Zone2_Short",
        wednesday="Strength",
        thursday="Rest",
        friday="Threshold",
        saturday="Zone2_Long",
        sunday="Rest",
    )

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli, ["morning", "--date", "2026-08-03"], input=_HIIT_NO_OVERRIDE
        )

    assert result.exit_code == 0, result.output
    assert "Recommendation:" in result.output
    assert "Explanation: Mock explanation for" in result.output

    engine = create_engine(str(db_path))
    metrics_row = MetricsRepository(engine).get_daily_metrics("2026-08-03")
    assert metrics_row["whoop_hrv_ms"] == 71.4
    assert metrics_row["muscle_soreness"] == 3

    rows = _decisions_for(db_path, "2026-08-03")
    assert len(rows) == 2
    assert rows[0]["llm_explanation"] is None  # pre-Ollama, crash-safe row
    assert rows[1]["llm_explanation"] is not None  # post-Ollama, complete row
    assert rows[0]["scheduled_session"] == "HIIT"
    assert rows[0]["recommendation"] == rows[1]["recommendation"]

    rationale = json.loads(rows[1]["rationale_json"])
    assert {"recovery_zone", "hrv_signal", "soreness_level", "rule_applied"} <= rationale.keys()


def test_morning_falls_back_to_session_type_flag_when_no_plan(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli,
            ["morning", "--date", "2026-08-05", "--session-type", "HIIT"],
            input=_HIIT_NO_OVERRIDE,
        )

    assert result.exit_code == 0, result.output
    rows = _decisions_for(db_path, "2026-08-05")
    assert rows[0]["scheduled_session"] == "HIIT"


def test_morning_errors_cleanly_with_no_plan_and_no_fallback(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(cli, ["morning", "--date", "2026-08-05"])

    assert result.exit_code != 0
    assert "No weekly plan covers" in result.output
    assert _decisions_for(db_path, "2026-08-05") == []


def test_morning_override_triggers_abort_and_persists_override_rationale(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    # HIIT: left_knee_pain=4 crosses the ABORT_STRENGTH_RUN/override threshold.
    override_input = "3\n2\n4\n4\n2\n2\n"
    with patch.dict(os.environ, _env(db_path), clear=True):
        result = runner.invoke(
            cli,
            ["morning", "--date", "2026-08-05", "--session-type", "HIIT"],
            input=override_input,
        )

    assert result.exit_code == 0, result.output
    assert "Override triggered" in result.output
    assert "Recommendation: ABORT" in result.output

    rows = _decisions_for(db_path, "2026-08-05")
    assert rows[0]["recommendation"] == "ABORT"
    rationale = json.loads(rows[0]["rationale_json"])
    assert "health_check_override" in rationale["rule_applied"]


def test_morning_prints_warn_banner_and_skips_second_row_when_ollama_degraded(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    degraded = ExplanationResult(
        explanation=None,
        degraded=True,
        banner="[Ollama offline -- start with: ollama serve]",
        severity="WARN",
    )
    with patch.dict(os.environ, _env(db_path), clear=True):
        with patch("apex_coach.cli.main.MockOllamaAdapter") as MockAdapterClass:
            MockAdapterClass.return_value.explain.return_value = degraded
            result = runner.invoke(
                cli,
                ["morning", "--date", "2026-08-05", "--session-type", "HIIT"],
                input=_HIIT_NO_OVERRIDE,
            )

    assert result.exit_code == 0, result.output
    assert "Recommendation:" in result.output
    assert "[WARN] [Ollama offline" in result.output
    assert "Explanation:" not in result.output

    rows = _decisions_for(db_path, "2026-08-05")
    assert len(rows) == 1  # only the pre-Ollama row — decision itself wasn't lost
    assert rows[0]["llm_explanation"] is None


def test_morning_decision_context_matches_api_contract_shape(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)
    _plan_week(
        runner,
        db_path,
        week_start="2026-08-03",
        monday="HIIT",
        tuesday="Zone2_Short",
        wednesday="Strength",
        thursday="Rest",
        friday="Threshold",
        saturday="Zone2_Long",
        sunday="Rest",
    )
    with patch.dict(os.environ, _env(db_path), clear=True):
        engine = create_engine(str(db_path))
        PlanRepository(engine).insert_monthly_target(
            month_start_date="2026-08-01",
            periodisation_phase="BUILD",
            load_target_total=500.0,
            race_date="2026-10-01",
        )

    captured = {}

    def _fake_explain(decision_context):
        captured["decision_context"] = decision_context
        return ExplanationResult(
            explanation="looks fine", degraded=False, banner=None, severity=None
        )

    with patch.dict(os.environ, _env(db_path), clear=True):
        with patch("apex_coach.cli.main.MockOllamaAdapter") as MockAdapterClass:
            MockAdapterClass.return_value.explain.side_effect = _fake_explain
            result = runner.invoke(
                cli, ["morning", "--date", "2026-08-03"], input=_HIIT_NO_OVERRIDE
            )

    assert result.exit_code == 0, result.output
    ctx = captured["decision_context"]
    assert set(ctx.keys()) == {
        "date",
        "athlete_context",
        "todays_plan",
        "biometrics",
        "morning_check",
        "decision",
        "weekly_context",
    }
    assert ctx["date"] == "2026-08-03"
    assert ctx["athlete_context"] == {
        "training_phase": "BUILD",
        "race_date": "2026-10-01",
        "weeks_to_race": 8,
    }
    assert ctx["todays_plan"]["scheduled_session"] == "HIIT"
    assert set(ctx["biometrics"].keys()) == {
        "whoop_recovery_pct",
        "whoop_hrv_ms",
        "hrv_30d_avg_ms",
        "hrv_delta_ms",
        "hrv_signal",
        "whoop_rhr_bpm",
        "whoop_strain_so_far",
    }
    assert ctx["morning_check"]["adaptive_checks"] == {
        "left_knee_pain": 1,
        "right_knee_pain": 2,
        "shin_calf_tightness": 2,
    }
    assert ctx["decision"]["recommendation"] in {"GO", "MODIFY", "MODALITY_SWAP", "ABORT"}
    assert ctx["weekly_context"]["sessions_remaining"][0] == "HIIT (today)"


def test_morning_real_requires_whoop_credentials(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    _init_db(runner, db_path)

    env = {**_env(db_path), "WHOOP_CLIENT_ID": "", "WHOOP_CLIENT_SECRET": ""}
    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(
            cli, ["morning", "--date", "2026-08-05", "--session-type", "HIIT", "--real"]
        )

    assert result.exit_code != 0
    assert "WHOOP_CLIENT_ID" in result.output


def test_morning_real_uses_real_whoop_and_ollama_adapters(tmp_path):
    db_path = tmp_path / "test.db"
    date = "2026-08-05"
    payload = MockWhoopAdapter().get_daily_payload(date)
    runner = CliRunner()
    _init_db(runner, db_path)

    env = {
        **_env(db_path),
        "WHOOP_CLIENT_ID": "test-client-id",
        "WHOOP_CLIENT_SECRET": "test-client-secret",
    }

    with patch.dict(os.environ, env, clear=True):
        with patch("apex_coach.cli.main.RealWhoopAdapter") as MockWhoopClass, patch(
            "apex_coach.cli.main.RealOllamaAdapter"
        ) as MockOllamaClass:
            MockWhoopClass.return_value.get_daily_payload.return_value = payload
            MockOllamaClass.return_value.explain.return_value = ExplanationResult(
                explanation="real-adapter explanation", degraded=False, banner=None, severity=None
            )
            result = runner.invoke(
                cli,
                ["morning", "--date", date, "--session-type", "HIIT", "--real"],
                input=_HIIT_NO_OVERRIDE,
            )

    assert result.exit_code == 0, result.output
    assert "Explanation: real-adapter explanation" in result.output
    MockWhoopClass.return_value.get_daily_payload.assert_called_once_with(date)
    MockOllamaClass.return_value.explain.assert_called_once()

    engine = create_engine(str(db_path))
    row = MetricsRepository(engine).get_daily_metrics(date)
    assert row["whoop_hrv_ms"] == payload.whoop_hrv_ms
