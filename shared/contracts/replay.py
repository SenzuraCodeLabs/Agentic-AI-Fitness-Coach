"""Replay protection: a Mongo-backed nonce store.

A signature proves a message was authored by a key holder. It does not prove
the message is *new*: anyone who captures a valid envelope can resend it
verbatim, and every signature check will pass. For a workout log that means a
duplicated session; for a decision envelope it could mean re-authorising an
action the Gatekeeper already consumed.

Two mechanisms close this together:

  expires_at  bounds the window in which a captured envelope is useful at all.
  message_id  makes each envelope single-use inside that window.

Neither suffices alone. Without expiry the nonce set would grow forever; without
the nonce a message could be replayed freely until it expired.

The check must be atomic. A read-then-write ("have I seen this? no, record it")
has a race: two concurrent copies of the same replayed envelope can both read
"unseen" before either writes. Instead this inserts first and treats a duplicate
key error as the detection signal, which pushes atomicity into the unique index
where the database guarantees it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError, PyMongoError

from shared.db import NONCES, get_db
from shared.logging import get_logger

log = get_logger("replay")


class ReplayGuard:
    """Single-use enforcement for envelope message IDs."""

    def __init__(self, db: AsyncIOMotorDatabase | None = None) -> None:
        self._db = db

    @property
    def db(self) -> AsyncIOMotorDatabase:
        return self._db if self._db is not None else get_db()

    async def is_replay(
        self,
        message_id: str,
        *,
        expires_at: datetime | None = None,
        sender: str | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        """Atomically claim ``message_id``. True means it was already used.

        The record is kept until ``expires_at``, after which the TTL index
        removes it. Retaining it exactly as long as the envelope is valid is
        what makes the store bounded: an envelope that outlives its nonce
        record would be replayable, and a nonce that outlives its envelope is
        wasted storage.
        """
        ttl = expires_at or (datetime.now(UTC) + timedelta(seconds=120))
        # TTL indexes need a naive-or-aware datetime Mongo can compare; store
        # UTC consistently.
        if ttl.tzinfo is not None:
            ttl = ttl.astimezone(UTC)

        try:
            await self.db[NONCES].insert_one(
                {
                    "message_id": message_id,
                    "expires_at": ttl,
                    "sender": sender,
                    "correlation_id": correlation_id,
                    "seen_at": datetime.now(UTC),
                }
            )
            return False
        except DuplicateKeyError:
            log.warning(
                "replay_detected",
                message_id=message_id,
                sender=sender,
                correlation_id=correlation_id,
            )
            return True
        except PyMongoError as exc:
            # Fail closed. If the nonce store is unavailable we cannot prove the
            # message is fresh, and treating an unverifiable message as valid
            # would silently disable replay protection during an outage.
            log.error("replay_store_unavailable", error=str(exc))
            raise


class InMemoryReplayGuard(ReplayGuard):
    """Process-local guard for unit tests and single-process benchmarks.

    Not suitable for production: with more than one worker each process would
    keep its own set, so a replay to a different worker would pass.
    """

    def __init__(self) -> None:  # noqa: D107
        super().__init__(db=None)
        self._seen: dict[str, datetime] = {}

    async def is_replay(
        self,
        message_id: str,
        *,
        expires_at: datetime | None = None,
        sender: str | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        # Emulate the TTL index so long-running tests do not leak memory.
        self._seen = {k: v for k, v in self._seen.items() if v > now}
        if message_id in self._seen:
            return True
        self._seen[message_id] = expires_at or (now + timedelta(seconds=120))
        return False
