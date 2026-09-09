"""Gateway authentication.

Runs against a real MongoDB test database. The password-hashing tests are
deliberately few: Argon2 is deliberately slow, so hashing in a tight loop would
make the suite crawl.
"""

from __future__ import annotations

import time

import pytest
from jose import jwt

from services.gateway.security import (
    create_access_token,
    decode_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)
from shared.config import get_settings
from shared.errors import AuthError

# --- Password hashing -------------------------------------------------------


def test_password_round_trip():
    stored = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", stored)
    assert not verify_password("wrong password entirely", stored)


def test_hash_is_argon2id():
    """Not bcrypt, not SHA: a fast hash is the wrong tool for passwords."""
    assert hash_password("test password 123").startswith("$argon2id$")


def test_same_password_hashes_differently():
    """A per-hash salt means identical passwords do not share a digest, so a
    leaked database cannot be attacked with a single rainbow table."""
    assert hash_password("same password") != hash_password("same password")


def test_hash_does_not_contain_the_password():
    assert "supersecret" not in hash_password("supersecret123")


def test_verification_of_a_corrupt_hash_returns_false():
    """Returns False rather than raising, so a caller cannot distinguish a
    corrupt record from a wrong password in a response."""
    assert not verify_password("anything", "not-a-valid-hash")


# --- JWT --------------------------------------------------------------------


def test_access_token_round_trip():
    token = create_access_token("user-123", "a@b.com")
    claims = decode_access_token(token)
    assert claims["sub"] == "user-123"
    assert claims["email"] == "a@b.com"
    assert claims["type"] == "access"


def test_expired_token_is_rejected():
    token = create_access_token("user-123", "a@b.com", minutes=-1)
    with pytest.raises(AuthError):
        decode_access_token(token)


def test_token_signed_with_another_key_is_rejected():
    forged = jwt.encode(
        {"sub": "attacker", "type": "access", "exp": int(time.time()) + 3600},
        "an-attacker-chosen-secret",
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        decode_access_token(forged)


def test_alg_none_token_is_rejected():
    """The classic JWT attack: an unsigned token claiming alg=none.

    The decoder pins the algorithm rather than trusting the token's header.
    """
    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "attacker", "type": "access", "exp": int(time.time()) + 3600}).encode()
    )
    forged = f"{header.decode().rstrip('=')}.{payload.decode().rstrip('=')}."

    with pytest.raises(AuthError):
        decode_access_token(forged)


def test_tampered_claims_are_rejected():
    token = create_access_token("user-123", "a@b.com")
    header, payload, signature = token.split(".")
    import base64
    import json

    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["sub"] = "someone-else"
    new_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")

    with pytest.raises(AuthError):
        decode_access_token(f"{header}.{new_payload}.{signature}")


def test_garbage_token_is_rejected():
    with pytest.raises(AuthError):
        decode_access_token("not.a.token")


def test_token_carries_a_unique_id():
    """A per-token jti lets a specific token be traced through the logs."""
    a = decode_access_token(create_access_token("u", "a@b.com"))
    b = decode_access_token(create_access_token("u", "a@b.com"))
    assert a["jti"] != b["jti"]


def test_access_token_expiry_matches_configuration():
    settings = get_settings()
    claims = decode_access_token(create_access_token("u", "a@b.com"))
    lifetime_minutes = (claims["exp"] - claims["iat"]) / 60
    assert lifetime_minutes == pytest.approx(settings.access_token_minutes, abs=0.1)


# --- Opaque tokens ----------------------------------------------------------


def test_opaque_tokens_are_unpredictable():
    tokens = {generate_opaque_token() for _ in range(200)}
    assert len(tokens) == 200
    assert all(len(t) >= 40 for t in tokens)


def test_token_hash_is_stable_and_hides_the_token():
    token = generate_opaque_token()
    assert hash_token(token) == hash_token(token)
    assert token not in hash_token(token)
    assert len(hash_token(token)) == 64
