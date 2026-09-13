"""Async MongoDB access via Motor.

One client per process, created lazily and reused: Motor's client owns a
connection pool, so constructing one per request would defeat pooling and leak
sockets. The client is safe to share across tasks.

Index creation lives here rather than in a migration tool because the index set
is small and declarative; ``ensure_indexes`` is idempotent and runs at startup.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.errors import PyMongoError

from shared.config import get_settings
from shared.logging import get_logger

log = get_logger("db")

_client: AsyncIOMotorClient | None = None


# --- Collection names -------------------------------------------------------
USERS = "users"
REFRESH_TOKENS = "refresh_tokens"
EMAIL_TOKENS = "email_tokens"
WORKOUTS = "workouts"
SESSIONS = "chat_sessions"
AUDIT_EVENTS = "audit_events"
NONCES = "envelope_nonces"
TELEMETRY = "telemetry"
RATE_LIMITS = "rate_limits"
DECISION_TRACES = "decision_traces"


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncIOMotorClient(
            settings.mongodb_uri.get_secret_value(),
            serverSelectionTimeoutMS=5000,
            uuidRepresentation="standard",
        )
    return _client


def get_db() -> AsyncIOMotorDatabase:
    """FastAPI dependency returning the application database handle."""
    return get_client()[get_settings().mongodb_db]


async def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


async def ping() -> bool:
    """Healthcheck: is the database reachable?"""
    try:
        await get_client().admin.command("ping")
        return True
    except PyMongoError as exc:
        log.warning("db_ping_failed", error=str(exc))
        return False


async def ensure_indexes() -> None:
    """Create every index the application relies on. Idempotent.

    TTL indexes (``expireAfterSeconds=0`` on a date field) let MongoDB expire
    nonces and one-time tokens itself, so no cleanup job is needed and a replay
    window cannot grow unbounded.
    """
    db = get_db()

    plans: dict[str, list[IndexModel]] = {
        "answer_cache": [
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expiry"),
            IndexModel([("user_id", ASCENDING)], name="by_user"),
        ],
        USERS: [
            IndexModel([("email", ASCENDING)], unique=True, name="uniq_email"),
        ],
        REFRESH_TOKENS: [
            IndexModel([("token_hash", ASCENDING)], unique=True, name="uniq_token_hash"),
            IndexModel([("user_id", ASCENDING)], name="by_user"),
            # Expired refresh tokens self-delete; revocation is a separate flag.
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expiry"),
        ],
        EMAIL_TOKENS: [
            IndexModel([("token_hash", ASCENDING)], unique=True, name="uniq_token_hash"),
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expiry"),
        ],
        WORKOUTS: [
            IndexModel(
                [("user_id", ASCENDING), ("session_date", DESCENDING)],
                name="by_user_date",
            ),
            IndexModel(
                [("user_id", ASCENDING), ("exercise", ASCENDING), ("session_date", DESCENDING)],
                name="by_user_exercise_date",
            ),
        ],
        AUDIT_EVENTS: [
            # The hash chain is ordered by seq; unique prevents a forked chain.
            IndexModel([("seq", ASCENDING)], unique=True, name="uniq_seq"),
            IndexModel([("correlation_id", ASCENDING)], name="by_correlation"),
            IndexModel([("created_at", DESCENDING)], name="by_time"),
        ],
        NONCES: [
            IndexModel([("message_id", ASCENDING)], unique=True, name="uniq_message_id"),
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expiry"),
        ],
        TELEMETRY: [
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="by_user_time"),
            IndexModel([("correlation_id", ASCENDING)], name="by_correlation"),
        ],
        RATE_LIMITS: [
            IndexModel([("key", ASCENDING)], name="by_key"),
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expiry"),
        ],
        DECISION_TRACES: [
            IndexModel([("message_id", ASCENDING)], unique=True, name="uniq_message_id"),
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="by_user_time"),
            # Traces are debugging evidence, not permanent records: 30 days.
            IndexModel([("created_at", ASCENDING)], expireAfterSeconds=2_592_000, name="ttl_30d"),
        ],
        SESSIONS: [
            IndexModel([("user_id", ASCENDING), ("updated_at", DESCENDING)], name="by_user_time"),
        ],
    }

    created: dict[str, Any] = {}
    for collection, models in plans.items():
        try:
            created[collection] = await db[collection].create_indexes(models)
        except PyMongoError as exc:
            # A conflicting pre-existing index should not stop the service.
            log.warning("index_creation_failed", collection=collection, error=str(exc))
    log.info("indexes_ensured", collections=list(created))
