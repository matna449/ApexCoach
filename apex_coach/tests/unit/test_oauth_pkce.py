import threading
import time

import httpx
import pytest

from apex_coach.adapters.oauth_pkce import generate_pkce_pair, generate_state, wait_for_callback


def test_generate_pkce_pair_produces_distinct_verifier_and_challenge():
    verifier, challenge = generate_pkce_pair()
    assert verifier != challenge
    assert len(verifier) >= 43  # base64url of 32 bytes, no padding
    assert "=" not in verifier
    assert "=" not in challenge


def test_generate_pkce_pair_is_random_each_time():
    v1, _ = generate_pkce_pair()
    v2, _ = generate_pkce_pair()
    assert v1 != v2


def test_generate_state_is_random_each_time():
    assert generate_state() != generate_state()


def test_wait_for_callback_captures_code_and_state():
    result_holder = {}

    def run_server():
        result_holder["result"] = wait_for_callback("localhost", 18080, "/callback", timeout_seconds=5)

    thread = threading.Thread(target=run_server)
    thread.start()
    time.sleep(0.2)  # let the server start listening

    response = httpx.get(
        "http://localhost:18080/callback", params={"code": "abc123", "state": "xyz"}
    )
    assert response.status_code == 200

    thread.join(timeout=5)
    result = result_holder["result"]
    assert result.code == "abc123"
    assert result.state == "xyz"
    assert result.error is None


def test_wait_for_callback_captures_error():
    result_holder = {}

    def run_server():
        result_holder["result"] = wait_for_callback("localhost", 18081, "/callback", timeout_seconds=5)

    thread = threading.Thread(target=run_server)
    thread.start()
    time.sleep(0.2)

    httpx.get("http://localhost:18081/callback", params={"error": "access_denied"})

    thread.join(timeout=5)
    assert result_holder["result"].error == "access_denied"


def test_wait_for_callback_times_out():
    with pytest.raises(TimeoutError):
        wait_for_callback("localhost", 18082, "/callback", timeout_seconds=1)
