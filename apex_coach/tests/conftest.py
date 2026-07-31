"""live_llm tests need a real Ollama instance with llama3.1:8b pulled —
skipped by default (SDD §7.2), run manually with --run-live-llm."""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-live-llm",
        action="store_true",
        default=False,
        help="run tests marked live_llm (requires a running local Ollama instance)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live-llm"):
        return
    skip_live = pytest.mark.skip(reason="need --run-live-llm to run (requires local Ollama)")
    for item in items:
        if "live_llm" in item.keywords:
            item.add_marker(skip_live)
