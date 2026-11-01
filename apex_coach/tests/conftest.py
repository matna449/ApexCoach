"""live_llm tests need a real Ollama instance with gemma4:latest pulled
(docs/adr/0022) — skipped by default (SDD §7.2), run manually with
--run-live-llm.

postgres tests need a throwaway database in APEX_TEST_POSTGRES_URL — skipped
by default, run with --run-postgres. They wipe that database, so they never
read DATABASE_URL, which may point at real data."""

import os

import pytest

from apex_coach.config.settings import normalize_database_url
from apex_coach.db.engine import create_engine
from apex_coach.db.schema import metadata

# web/backend reads these at import. Set after the imports above, which load .env.
os.environ["APEX_ALLOW_UNAUTHENTICATED"] = "true"
os.environ.pop("APEX_API_KEY", None)
os.environ.pop("VERCEL", None)


def pytest_addoption(parser):
    parser.addoption(
        "--run-live-llm",
        action="store_true",
        default=False,
        help="run tests marked live_llm (requires a running local Ollama instance)",
    )
    parser.addoption(
        "--run-postgres",
        action="store_true",
        default=False,
        help="run tests marked postgres (requires a throwaway APEX_TEST_POSTGRES_URL)",
    )


def pytest_collection_modifyitems(config, items):
    skips = {
        "live_llm": (
            config.getoption("--run-live-llm"),
            "need --run-live-llm to run (requires local Ollama)",
        ),
        "postgres": (
            config.getoption("--run-postgres"),
            "need --run-postgres to run (requires APEX_TEST_POSTGRES_URL)",
        ),
    }
    for marker, (enabled, reason) in skips.items():
        if enabled:
            continue
        skip = pytest.mark.skip(reason=reason)
        for item in items:
            if marker in item.keywords:
                item.add_marker(skip)


@pytest.fixture
def postgres_url():
    return normalize_database_url(os.environ["APEX_TEST_POSTGRES_URL"])


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def repository_engine(request):
    """An empty schema on each dialect the repositories must work on."""
    if request.param == "sqlite":
        engine = create_engine(":memory:")
        metadata.create_all(engine)
        yield engine
        return

    engine = create_engine(request.getfixturevalue("postgres_url"))
    metadata.drop_all(engine)
    metadata.create_all(engine)
    yield engine
    metadata.drop_all(engine)
    engine.dispose()
