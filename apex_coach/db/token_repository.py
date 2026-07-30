"""Sole writer for oauth_tokens (ADR-0003). Fernet encryption at rest (ADR-0005)."""

import base64
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from apex_coach.db.schema import oauth_tokens

# Domain-separation salt for a single-secret, single-machine KDF input — not a
# password hash defending against rainbow tables across many users. See ADR-0005.
_KDF_SALT = b"apex-coach-oauth-token-encryption-v1"

REFRESH_THRESHOLD = timedelta(seconds=60)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        stmt = sa.dialects.sqlite.insert(oauth_tokens).values(
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
        }

    def needs_refresh(self, provider: str) -> bool:
        token = self.get_token(provider)
        if token is None:
            raise ValueError(f"no stored token for provider {provider!r}")

        expires_at = datetime.fromisoformat(token["expires_at"])
        return datetime.now(timezone.utc) >= expires_at - REFRESH_THRESHOLD
