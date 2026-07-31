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
    whoop_redirect_uri: str = "http://localhost:8080/callback"


def get_settings() -> Settings:
    return Settings(
        apex_encryption_key=os.environ["APEX_ENCRYPTION_KEY"],
        database_url=os.getenv("DATABASE_URL", "sqlite:///./apex_coach.db"),
        whoop_client_id=os.getenv("WHOOP_CLIENT_ID"),
        whoop_client_secret=os.getenv("WHOOP_CLIENT_SECRET"),
        whoop_redirect_uri=os.getenv("WHOOP_REDIRECT_URI", "http://localhost:8080/callback"),
    )
