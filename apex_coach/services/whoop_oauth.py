"""Hosted WHOOP OAuth flow (F21 spec §5): the redirect lands on our own callback
route, so the CLI's paste-back step (docs/adr/0018) is not needed."""

from datetime import datetime, timedelta, timezone

import httpx

from apex_coach.adapters.errors import AdapterUnavailableError
from apex_coach.adapters.oauth_pkce import generate_pkce_pair, generate_state
from apex_coach.adapters.whoop_adapter import build_authorization_url, exchange_code_for_tokens
from apex_coach.db.token_repository import TokenRepository


class InvalidOAuthStateError(Exception):
    """The callback's state is unknown, expired or already used."""


def start_authorization(token_repo: TokenRepository, client_id: str, redirect_uri: str) -> str:
    code_verifier, code_challenge = generate_pkce_pair()
    state = generate_state()
    token_repo.save_pending_state(state, code_verifier)
    return build_authorization_url(client_id, redirect_uri, state, code_challenge)


def complete_authorization(
    token_repo: TokenRepository,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    state: str,
) -> None:
    code_verifier = token_repo.consume_pending_state(state)
    if code_verifier is None:
        raise InvalidOAuthStateError("unknown or expired OAuth state")

    try:
        tokens = exchange_code_for_tokens(
            client_id, client_secret, redirect_uri, code, code_verifier
        )
    except httpx.HTTPError as e:
        raise AdapterUnavailableError("WHOOP token exchange failed") from e

    token_repo.save_token(
        provider="WHOOP",
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_at=(
            datetime.now(timezone.utc) + timedelta(seconds=tokens["expires_in"])
        ).isoformat(),
        scope=tokens.get("scope", ""),
    )
