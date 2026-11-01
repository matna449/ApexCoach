"""F21.9: INTERVALS_ICU_API_KEY wins over the stored key (F21 spec §3.4)."""

from unittest.mock import patch

import click
import pytest

from apex_coach.cli.main import (
    _build_activity_sync_adapter,
    _build_plan_export_adapter,
    _intervals_icu_api_key,
)
from apex_coach.config.settings import Settings, get_settings
from apex_coach.db.engine import create_engine
from apex_coach.db.schema import metadata
from apex_coach.db.token_repository import TokenRepository

PROFILE = {"activity_sync_provider": "INTERVALS_ICU"}


@pytest.fixture
def engine():
    engine = create_engine(":memory:")
    metadata.create_all(engine)
    return engine


def _settings(key=None):
    return Settings(apex_encryption_key="test-key", database_url="unused", intervals_icu_api_key=key)


def _store(engine, key="stored-key"):
    TokenRepository(engine, "test-key").save_token(
        "INTERVALS_ICU", key, "", "2099-01-01T00:00:00+00:00", ""
    )


def test_env_var_wins_over_the_stored_key(engine):
    _store(engine)

    assert _intervals_icu_api_key(engine, _settings("env-key")) == "env-key"


def test_stored_key_is_the_fallback(engine):
    _store(engine)

    assert _intervals_icu_api_key(engine, _settings()) == "stored-key"
    assert _intervals_icu_api_key(engine, _settings("")) == "stored-key"


def test_neither_gives_the_existing_error_and_names_both_options(engine):
    with pytest.raises(click.ClickException) as e:
        _intervals_icu_api_key(engine, _settings())

    assert e.value.message.startswith("No intervals.icu API key stored")
    assert "connect-intervals-icu" in e.value.message
    assert "INTERVALS_ICU_API_KEY" in e.value.message


@pytest.mark.parametrize("build", [_build_activity_sync_adapter, _build_plan_export_adapter])
def test_real_adapters_use_the_env_var_with_nothing_stored(engine, build):
    with patch("apex_coach.cli.main.RealIntervalsIcuAdapter") as adapter:
        build(engine, _settings("env-key"), PROFILE, real=True)

    adapter.assert_called_once_with("env-key")


@pytest.mark.parametrize("build", [_build_activity_sync_adapter, _build_plan_export_adapter])
def test_real_adapters_fall_back_to_the_stored_key(engine, build):
    _store(engine)

    with patch("apex_coach.cli.main.RealIntervalsIcuAdapter") as adapter:
        build(engine, _settings(), PROFILE, real=True)

    adapter.assert_called_once_with("stored-key")


def test_settings_read_the_env_var(monkeypatch):
    monkeypatch.setenv("APEX_ENCRYPTION_KEY", "test-key")
    monkeypatch.setenv("INTERVALS_ICU_API_KEY", "env-key")

    assert get_settings().intervals_icu_api_key == "env-key"
