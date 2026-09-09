"""Password hashing and token issuance.

ARGON2 RATHER THAN BCRYPT OR SHA
--------------------------------
A fast hash is the wrong tool for passwords: speed is the attacker's advantage
once a database leaks. Argon2id is memory-hard, so an attacker cannot simply
throw GPUs at it; each guess costs real RAM. It won the Password Hashing
Competition and is the current OWASP recommendation.

Never SHA-256: it is designed to be fast, which is precisely wrong here.

REFRESH TOKENS ARE STORED HASHED
--------------------------------
The database stores SHA-256 of the refresh token, not the token. A read-only
leak therefore does not yield usable tokens. SHA-256 is appropriate here, in
contrast to passwords, because the token is 32 bytes of cryptographic
randomness: there is no dictionary to attack, so the slowness of Argon2 would
buy nothing and cost a hash on every refresh.

ROTATION AND REUSE DETECTION
----------------------------
Each refresh mints a new token and revokes the old one. If a revoked token is
ever presented again, that is evidence it was stolen (the legitimate client
would have moved on), so the entire family is revoked, forcing re-login.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from jose import JWTError, jwt
from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.config import get_settings
from shared.db import EMAIL_TOKENS, REFRESH_TOKENS
from shared.errors import AuthError
from shared.logging import get_logger

log = get_logger("gateway.security")

# Parameters follow the OWASP cheat-sheet baseline: 64 MiB of memory, 3
# iterations, 4 lanes. Memory cost is the parameter that matters against GPU
# cracking.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

ACCESS_TOKEN_TYPE = "access"  # noqa: S105 - a claim label, not a credential
REFRESH_TOKEN_TYPE = "refresh"  # noqa: S105


def hash_password(password: str) -> str:
    """Return an Argon2id hash. The salt is generated per call and embedded."""
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time-ish verification via argon2.

    Returns False rather than raising so callers cannot accidentally
    distinguish "wrong password" from "corrupt hash" in a response.
    """
    try:
        _hasher.verify(stored_hash, password)
        return True
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True when the hash used weaker parameters than the current policy."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except (InvalidHashError, ValueError):
        return False


# --- JWT --------------------------------------------------------------------


def create_access_token(user_id: str, email: str, *, minutes: int | None = None) -> str:
    """Mint a short-lived access token.

    Short expiry is the main defence for a stateless token: it cannot be
    revoked, so its value to a thief is bounded by its lifetime. Revocation
    lives on the refresh token, which is stored server-side.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    expiry = now + timedelta(minutes=minutes or settings.access_token_minutes)

    claims = {
        "sub": user_id,
        "email": email,
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(expiry.timestamp()),
        # A per-token id, so a specific token can be traced through the logs.
        "jti": secrets.token_urlsafe(8),
    }
    return jwt.encode(
        claims,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Validate and decode an access token.

    The algorithm is pinned. Accepting the token's own ``alg`` header is the
    classic JWT vulnerability: an attacker sets ``alg: none`` or swaps HS256
    for RS256 to have their forged token verified against a public key.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],  # pinned, never from the header
        )
    except JWTError as exc:
        raise AuthError("invalid or expired token") from exc

    if claims.get("type") != ACCESS_TOKEN_TYPE:
        # Prevents presenting a refresh token where an access token is required.
        raise AuthError("wrong token type")
    return claims


# --- Opaque tokens (refresh, email verification, password reset) ------------


def generate_opaque_token() -> str:
    """32 bytes of CSPRNG entropy, URL-safe.

    ``secrets`` rather than ``random``: the latter is a Mersenne Twister whose
    internal state can be recovered from a few outputs, so its values are
    predictable.
    """
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 of a token, for storage. See the module docstring."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def store_refresh_token(
    db: AsyncIOMotorDatabase,
    user_id: str,
    *,
    family_id: str | None = None,
) -> str:
    """Issue a refresh token and record its hash.

    ``family_id`` groups tokens descended from one login, so reuse detection
    can revoke the whole lineage rather than a single token.
    """
    settings = get_settings()
    token = generate_opaque_token()
    now = datetime.now(UTC)

    await db[REFRESH_TOKENS].insert_one(
        {
            "token_hash": hash_token(token),
            "user_id": user_id,
            "family_id": family_id or secrets.token_urlsafe(12),
            "created_at": now,
            "expires_at": now + timedelta(days=settings.refresh_token_days),
            "revoked": False,
            "used_at": None,
        }
    )
    return token


async def rotate_refresh_token(db: AsyncIOMotorDatabase, token: str) -> tuple[str, str]:
    """Exchange a refresh token for a new pair. Detects reuse.

    Returns ``(user_id, new_refresh_token)``.
    """
    record = await db[REFRESH_TOKENS].find_one({"token_hash": hash_token(token)})
    if record is None:
        raise AuthError("invalid refresh token")

    if record.get("revoked"):
        # A revoked token being presented again means it was captured: the
        # legitimate client would already hold its successor. Revoke the whole
        # family so the thief and the victim are both forced to re-authenticate.
        log.warning(
            "refresh_token_reuse_detected",
            user_id=record.get("user_id"),
            family_id=record.get("family_id"),
        )
        await db[REFRESH_TOKENS].update_many(
            {"family_id": record.get("family_id")},
            {"$set": {"revoked": True, "revoked_reason": "reuse_detected"}},
        )
        raise AuthError("refresh token has been revoked")

    expires_at = record.get("expires_at")
    if expires_at and expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        raise AuthError("refresh token expired")

    await db[REFRESH_TOKENS].update_one(
        {"_id": record["_id"]},
        {"$set": {"revoked": True, "used_at": datetime.now(UTC)}},
    )
    new_token = await store_refresh_token(db, record["user_id"], family_id=record.get("family_id"))
    return record["user_id"], new_token


async def revoke_all_refresh_tokens(db: AsyncIOMotorDatabase, user_id: str) -> int:
    result = await db[REFRESH_TOKENS].update_many(
        {"user_id": user_id, "revoked": False},
        {"$set": {"revoked": True, "revoked_reason": "logout_all"}},
    )
    return result.modified_count


# --- Single-use email tokens ------------------------------------------------


async def create_email_token(
    db: AsyncIOMotorDatabase,
    user_id: str,
    purpose: str,
    *,
    ttl_minutes: int = 60,
) -> str:
    """Issue a single-use, time-limited token for email verification or reset.

    Any outstanding token for the same purpose is invalidated first, so
    requesting a new reset link cannot leave an older one live.
    """
    await db[EMAIL_TOKENS].delete_many({"user_id": user_id, "purpose": purpose})

    token = generate_opaque_token()
    now = datetime.now(UTC)
    await db[EMAIL_TOKENS].insert_one(
        {
            "token_hash": hash_token(token),
            "user_id": user_id,
            "purpose": purpose,
            "created_at": now,
            "expires_at": now + timedelta(minutes=ttl_minutes),
            "used": False,
        }
    )
    return token


async def consume_email_token(db: AsyncIOMotorDatabase, token: str, purpose: str) -> str | None:
    """Atomically validate and consume a token. Returns the user id, or None.

    ``find_one_and_update`` with ``used: False`` in the filter makes this a
    single atomic operation: two concurrent uses of the same link cannot both
    succeed, because only one update can match.
    """
    now = datetime.now(UTC)
    record = await db[EMAIL_TOKENS].find_one_and_update(
        {
            "token_hash": hash_token(token),
            "purpose": purpose,
            "used": False,
            "expires_at": {"$gt": now},
        },
        {"$set": {"used": True, "used_at": now}},
    )
    return record["user_id"] if record else None
