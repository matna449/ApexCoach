from apex_coach.adapters.oauth_pkce import generate_pkce_pair, generate_state


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
