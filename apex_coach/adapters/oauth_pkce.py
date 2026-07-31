"""OAuth 2.0 PKCE helpers, shared across providers (WHOOP §2.1, Strava §3.1).

A local-server callback capture used to live here (superseded — see
docs/adr/0018's 2026-07-31 update and #35: WHOOP rejects
http://localhost redirect URIs, so the authorization code is now
collected via a hosted callback landing page + manual paste instead).
"""

import base64
import hashlib
import secrets


def generate_pkce_pair() -> tuple[str, str]:
    """Returns (code_verifier, code_challenge) — S256 method."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return code_verifier, code_challenge


def generate_state() -> str:
    return secrets.token_urlsafe(16)
