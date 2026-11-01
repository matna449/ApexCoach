"""Loads .env and exposes a typed config object (SDD §3.1, §6.3).

Extended by later tickets (F02 OAuth, F09 Ollama) as they need more of
the documented environment variables.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    apex_encryption_key: str
    database_url: str
    whoop_client_id: str | None = None
    whoop_client_secret: str | None = None
    whoop_redirect_uri: str = "https://matna449.github.io/ApexCoach/callback.html"
    strava_client_id: str | None = None
    strava_client_secret: str | None = None
    strava_redirect_uri: str = "https://matna449.github.io/ApexCoach/callback.html"
    apex_api_key: str | None = None
    allow_unauthenticated: bool = False


def normalize_database_url(url: str) -> str:
    """Neon and Vercel hand out postgres:// or postgresql:// URLs; SQLAlchemy
    needs the psycopg driver named explicitly."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


def get_settings() -> Settings:
    return Settings(
        apex_encryption_key=os.environ["APEX_ENCRYPTION_KEY"],
        database_url=normalize_database_url(
            os.getenv("DATABASE_URL", "sqlite:///./apex_coach.db")
        ),
        whoop_client_id=os.getenv("WHOOP_CLIENT_ID"),
        whoop_client_secret=os.getenv("WHOOP_CLIENT_SECRET"),
        whoop_redirect_uri=os.getenv(
            "WHOOP_REDIRECT_URI", "https://matna449.github.io/ApexCoach/callback.html"
        ),
        strava_client_id=os.getenv("STRAVA_CLIENT_ID"),
        strava_client_secret=os.getenv("STRAVA_CLIENT_SECRET"),
        strava_redirect_uri=os.getenv(
            "STRAVA_REDIRECT_URI", "https://matna449.github.io/ApexCoach/callback.html"
        ),
        apex_api_key=os.getenv("APEX_API_KEY"),
        # Local development only, where the React frontend sends no key.
        allow_unauthenticated=(
            os.getenv("APEX_ALLOW_UNAUTHENTICATED") == "true" and "VERCEL" not in os.environ
        ),
    )
