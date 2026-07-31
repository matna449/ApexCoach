import os
from unittest.mock import patch

from click.testing import CliRunner

from apex_coach.adapters.whoop_adapter import MockWhoopAdapter
from apex_coach.cli.main import cli
from apex_coach.db.engine import create_engine
from apex_coach.db.metrics_repository import MetricsRepository


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


def _env(db_path):
    return {
        **os.environ,
        "APEX_ENCRYPTION_KEY": "test",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "WHOOP_CLIENT_ID": "dummy-client-id",
        "WHOOP_CLIENT_SECRET": "dummy-client-secret",
    }


def test_whoop_smoke_real_persists_all_five_whoop_fields_to_daily_metrics(tmp_path):
    db_path = tmp_path / "test.db"
    date = "2026-07-30"
    payload = MockWhoopAdapter().get_daily_payload(date)
    runner = CliRunner()

    with patch.dict(os.environ, _env(db_path), clear=True):
        init_result = runner.invoke(cli, ["init-db"])
        assert init_result.exit_code == 0

        with patch("apex_coach.cli.main.RealWhoopAdapter") as MockAdapterClass:
            MockAdapterClass.return_value.get_daily_payload.return_value = payload
            result = runner.invoke(cli, ["whoop-smoke", "--date", date, "--real"])

        assert result.exit_code == 0, result.output
        assert f"Persisted to daily_metrics for {date}." in result.output

        engine = create_engine(str(db_path))
        row = MetricsRepository(engine).get_daily_metrics(date)

    assert row is not None
    assert row["whoop_recovery_pct"] == payload.whoop_recovery_pct
    assert row["whoop_hrv_ms"] == payload.whoop_hrv_ms
    assert row["whoop_rhr_bpm"] == payload.whoop_rhr_bpm
    assert row["whoop_strain"] == payload.whoop_strain
    assert row["whoop_sleep_hours"] == payload.whoop_sleep_hours


def test_whoop_smoke_real_upsert_does_not_clobber_health_check_fields(tmp_path):
    db_path = tmp_path / "test.db"
    date = "2026-07-30"
    payload = MockWhoopAdapter().get_daily_payload(date)
    runner = CliRunner()

    with patch.dict(os.environ, _env(db_path), clear=True):
        init_result = runner.invoke(cli, ["init-db"])
        assert init_result.exit_code == 0

        engine = create_engine(str(db_path))
        metrics_repo = MetricsRepository(engine)
        metrics_repo.upsert_daily_metrics(
            date,
            muscle_soreness=3,
            subjective_energy=7,
            sleep_quality_felt=4,
            health_check_json='{"note": "felt fine"}',
        )

        with patch("apex_coach.cli.main.RealWhoopAdapter") as MockAdapterClass:
            MockAdapterClass.return_value.get_daily_payload.return_value = payload
            result = runner.invoke(cli, ["whoop-smoke", "--date", date, "--real"])

        assert result.exit_code == 0, result.output

        row = metrics_repo.get_daily_metrics(date)

    assert row is not None
    # WHOOP fields populated by this fetch.
    assert row["whoop_recovery_pct"] == payload.whoop_recovery_pct
    assert row["whoop_hrv_ms"] == payload.whoop_hrv_ms
    assert row["whoop_rhr_bpm"] == payload.whoop_rhr_bpm
    assert row["whoop_strain"] == payload.whoop_strain
    assert row["whoop_sleep_hours"] == payload.whoop_sleep_hours
    # Health-check fields set by the earlier writer are untouched.
    assert row["muscle_soreness"] == 3
    assert row["subjective_energy"] == 7
    assert row["sleep_quality_felt"] == 4
    assert row["health_check_json"] == '{"note": "felt fine"}'
