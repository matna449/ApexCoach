"""Sole writer for oauth_tokens (ADR-0003). Fernet encryption at rest (ADR-0005)."""

import base64
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from apex_coach.db.schema import oauth_pending_states, oauth_tokens
from apex_coach.db.upsert import dialect_insert

# Domain-separation salt for a single-secret, single-machine KDF input — not a
# password hash defending against rainbow tables across many users. See ADR-0005.
_KDF_SALT = b"apex-coach-oauth-token-encryption-v1"

REFRESH_THRESHOLD = timedelta(seconds=60)
PENDING_STATE_TTL = timedelta(minutes=10)
REAUTH_REQUIRED = "REAUTH_REQUIRED"


class TokenRefreshRejectedError(Exception):
    """The provider refuses the refresh token. Only a new authorization helps."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_expiring(expires_at: str) -> bool:
    return datetime.now(timezone.utc) >= datetime.fromisoformat(expires_at) - REFRESH_THRESHOLD


def _derive_fernet_key(apex_encryption_key: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        iterations=480_000,
    )
    key_bytes = kdf.derive(apex_encryption_key.encode("utf-8"))
    return base64.urlsafe_b64encode(key_bytes)


class TokenRepository:
    def __init__(self, engine: sa.engine.Engine, apex_encryption_key: str):
        self._engine = engine
        self._fernet = Fernet(_derive_fernet_key(apex_encryption_key))

    def save_token(
        self,
        provider: str,
        access_token: str,
        refresh_token: str,
        expires_at: str,
        scope: str,
    ) -> None:
        stmt = dialect_insert(self._engine, oauth_tokens).values(
            provider=provider,
            access_token=self._fernet.encrypt(access_token.encode("utf-8")).decode(
                "utf-8"
            ),
            refresh_token=self._fernet.encrypt(
                refresh_token.encode("utf-8")
            ).decode("utf-8"),
            expires_at=expires_at,
            scope=scope,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[oauth_tokens.c.provider],
            set_={
                "access_token": stmt.excluded.access_token,
                "refresh_token": stmt.excluded.refresh_token,
                "expires_at": stmt.excluded.expires_at,
                "scope": stmt.excluded.scope,
                # onupdate=_now_iso on the column only fires for Core Update()
                # statements, not ON CONFLICT DO UPDATE — set it explicitly.
                "updated_at": _now_iso(),
                "sync_status": None,
            },
        )
        with self._engine.begin() as conn:
            conn.execute(stmt)

    def get_token(self, provider: str) -> dict | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.select(oauth_tokens).where(oauth_tokens.c.provider == provider)
            ).one_or_none()

        if row is None:
            return None

        return {
            "provider": row.provider,
            "access_token": self._fernet.decrypt(
                row.access_token.encode("utf-8")
            ).decode("utf-8"),
            "refresh_token": self._fernet.decrypt(
                row.refresh_token.encode("utf-8")
            ).decode("utf-8"),
            "expires_at": row.expires_at,
            "scope": row.scope,
            "sync_status": row.sync_status,
        }

    def needs_refresh(self, provider: str) -> bool:
        token = self.get_token(provider)
        if token is None:
            raise ValueError(f"no stored token for provider {provider!r}")

        return _is_expiring(token["expires_at"])

    def get_valid_access_token(
        self, provider: str, refresh_fn: Callable[[str], dict]
    ) -> str:
        """Refreshes under a lock, because providers that rotate refresh tokens
        reject the second of two concurrent refreshes (F21 spec §5.1). refresh_fn
        takes the refresh token, returns the token response and raises
        TokenRefreshRejectedError when the provider refuses it."""
        token = self.get_token(provider)
        if token is None:
            raise ValueError(f"no stored token for provider {provider!r}")
        if not _is_expiring(token["expires_at"]):
            return token["access_token"]

        with self._engine.connect() as conn:
            if conn.dialect.name == "sqlite":
                # with_for_update() compiles to nothing on SQLite.
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            row = conn.execute(
                sa.select(oauth_tokens)
                .where(oauth_tokens.c.provider == provider)
                .with_for_update()
            ).one()

            # Another worker may have refreshed while this one waited.
            if not _is_expiring(row.expires_at):
                conn.commit()
                return self._decrypt(row.access_token)
            if row.sync_status == REAUTH_REQUIRED:
                conn.commit()
                raise TokenRefreshRejectedError(f"{provider} needs re-authorization")

            try:
                response = refresh_fn(self._decrypt(row.refresh_token))
            except TokenRefreshRejectedError:
                conn.execute(
                    oauth_tokens.update()
                    .where(oauth_tokens.c.provider == provider)
                    .values(sync_status=REAUTH_REQUIRED)
                )
                conn.commit()
                raise

            conn.execute(
                oauth_tokens.update()
                .where(oauth_tokens.c.provider == provider)
                .values(
                    access_token=self._encrypt(response["access_token"]),
                    refresh_token=self._encrypt(
                        response.get("refresh_token") or self._decrypt(row.refresh_token)
                    ),
                    expires_at=(
                        datetime.now(timezone.utc) + timedelta(seconds=response["expires_in"])
                    ).isoformat(),
                    scope=response.get("scope") or row.scope,
                    sync_status=None,
                )
            )
            conn.commit()
            return response["access_token"]

    def save_pending_state(self, state: str, code_verifier: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                oauth_pending_states.insert().values(
                    state=state, code_verifier=self._encrypt(code_verifier)
                )
            )

    def consume_pending_state(self, state: str) -> str | None:
        """Single use: the delete is atomic, so only one caller gets the verifier."""
        with self._engine.begin() as conn:
            row = conn.execute(
                oauth_pending_states.delete()
                .where(oauth_pending_states.c.state == state)
                .returning(oauth_pending_states.c.code_verifier, oauth_pending_states.c.created_at)
            ).one_or_none()

        if row is None:
            return None
        age = datetime.now(timezone.utc) - datetime.fromisoformat(row.created_at)
        return self._decrypt(row.code_verifier) if age <= PENDING_STATE_TTL else None

    def _encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def _decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
