"""Default-deny API auth (F21 spec §3.3): attached to the whole app, so a route
added later is protected without further code."""

import hmac
from collections.abc import Callable

from fastapi import HTTPException, Request

from apex_coach.config.settings import Settings

# Each of these is protected by its own mechanism, see the spec's table.
PUBLIC_PATHS = frozenset(
    {
        "/api/health",
        "/webhooks/whoop",
        "/auth/whoop/start",
        "/auth/whoop/callback",
        "/api/cron/whoop-reconcile",
    }
)


def require_api_key(settings: Settings) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        # Exact match, never by prefix: /api/health/daily must stay protected.
        # scope["path"] is the same value the router matched on.
        if request.scope["path"] in PUBLIC_PATHS:
            return

        if not settings.apex_api_key:
            if settings.allow_unauthenticated:
                return
            raise HTTPException(status_code=503, detail="APEX_API_KEY is not configured.")

        scheme, _, key = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            key.encode(), settings.apex_api_key.encode()
        ):
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid API key.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return dependency
