"""Loads .env and exposes a typed config object (SDD §3.1, §6.3).

Extended by later tickets (F01/F02 OAuth, F09 Ollama) as they need more
of the documented environment variables. Only what F10.2 needs exists here.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    apex_encryption_key: str
    database_url: str


def get_settings() -> Settings:
    apex_encryption_key = os.environ["APEX_ENCRYPTION_KEY"]
    database_url = os.getenv("DATABASE_URL", "sqlite:///./apex_coach.db")
    return Settings(
        apex_encryption_key=apex_encryption_key,
        database_url=database_url,
    )
