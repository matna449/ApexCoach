from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from apex_coach.db.schema import metadata, oauth_tokens
from apex_coach.db.token_repository import TokenRepository

ENCRYPTION_KEY = "test-passphrase-not-for-production"


@pytest.fixture
def repo():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    return TokenRepository(engine, ENCRYPTION_KEY)


def _future_iso(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def test_save_and_get_round_trips_decrypted_values(repo):
    repo.save_token(
        provider="WHOOP",
        access_token="access-123",
        refresh_token="refresh-456",
        expires_at=_future_iso(3600),
        scope="read:recovery",
    )

    token = repo.get_token("WHOOP")

    assert token["access_token"] == "access-123"
    assert token["refresh_token"] == "refresh-456"
    assert token["scope"] == "read:recovery"


def test_tokens_are_encrypted_at_rest(repo):
    repo.save_token(
        provider="WHOOP",
        access_token="super-secret-access-token",
        refresh_token="super-secret-refresh-token",
        expires_at=_future_iso(3600),
        scope="read:recovery",
    )

    with repo._engine.begin() as conn:
        row = conn.execute(
            sa.select(oauth_tokens).where(oauth_tokens.c.provider == "WHOOP")
        ).one()

    assert "super-secret-access-token" not in row.access_token
    assert "super-secret-refresh-token" not in row.refresh_token


def test_save_token_upserts_one_row_per_provider(repo):
    repo.save_token(
        provider="WHOOP",
        access_token="old-token",
        refresh_token="old-refresh",
        expires_at=_future_iso(3600),
        scope="read:recovery",
    )
    repo.save_token(
        provider="WHOOP",
        access_token="new-token",
        refresh_token="new-refresh",
        expires_at=_future_iso(7200),
        scope="read:recovery read:sleep",
    )

    with repo._engine.begin() as conn:
        count = conn.execute(
            sa.select(sa.func.count())
            .select_from(oauth_tokens)
            .where(oauth_tokens.c.provider == "WHOOP")
        ).scalar_one()

    assert count == 1
    assert repo.get_token("WHOOP")["access_token"] == "new-token"


def test_needs_refresh_false_when_far_from_expiry(repo):
    repo.save_token(
        provider="WHOOP",
        access_token="a",
        refresh_token="r",
        expires_at=_future_iso(3600),
        scope="read:recovery",
    )
    assert repo.needs_refresh("WHOOP") is False


def test_needs_refresh_true_within_60_seconds_of_expiry(repo):
    repo.save_token(
        provider="WHOOP",
        access_token="a",
        refresh_token="r",
        expires_at=_future_iso(30),
        scope="read:recovery",
    )
    assert repo.needs_refresh("WHOOP") is True


def test_needs_refresh_true_when_already_expired(repo):
    repo.save_token(
        provider="WHOOP",
        access_token="a",
        refresh_token="r",
        expires_at=_future_iso(-10),
        scope="read:recovery",
    )
    assert repo.needs_refresh("WHOOP") is True


def test_needs_refresh_raises_for_unknown_provider(repo):
    with pytest.raises(ValueError):
        repo.needs_refresh("STRAVA")


def test_whoop_and_strava_tokens_are_independent(repo):
    repo.save_token(
        provider="WHOOP",
        access_token="whoop-token",
        refresh_token="whoop-refresh",
        expires_at=_future_iso(3600),
        scope="read:recovery",
    )
    repo.save_token(
        provider="STRAVA",
        access_token="strava-token",
        refresh_token="strava-refresh",
        expires_at=_future_iso(3600),
        scope="activity:read",
    )

    assert repo.get_token("WHOOP")["access_token"] == "whoop-token"
    assert repo.get_token("STRAVA")["access_token"] == "strava-token"
