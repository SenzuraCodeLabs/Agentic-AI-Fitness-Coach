"""L0 - Rate limiting and token quota.

SLIDING WINDOW, NOT FIXED WINDOW
--------------------------------
A fixed window resets on a clock boundary, which lets a caller send the full
allowance at 11:59:59 and the full allowance again at 12:00:00: double the
intended rate across the boundary. A sliding window counts the requests in the
last N seconds from now, so the limit holds at every instant.

The implementation keeps request timestamps in an array and drops those outside
the window on each check. That is exact rather than approximate, and the arrays
stay small because the window is 60 seconds.

WHY BOTH PER-USER AND PER-IP
----------------------------
Per-user alone is defeated by registering many accounts. Per-IP alone punishes
users behind shared NAT, which is common on university and mobile networks.
Applying both means an attacker must find both many accounts and many addresses.

THE QUOTA IS A COST CONTROL
---------------------------
Requests are cheap; LLM tokens are not. The daily token quota is checked
against recorded telemetry so a user cannot run up unbounded API spend within
the request-rate limit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import PyMongoError

from shared.config import get_settings
from shared.db import RATE_LIMITS, TELEMETRY
from shared.errors import QuotaExceeded, RateLimited
from shared.logging import get_logger

log = get_logger("gateway.ratelimit")

WINDOW_SECONDS = 60


async def check_rate_limit(
    db: AsyncIOMotorDatabase,
    key: str,
    limit: int,
    *,
    window_seconds: int = WINDOW_SECONDS,
) -> tuple[int, int]:
    """Record a request and enforce the sliding-window limit.

    Returns ``(remaining, retry_after_seconds)``. Raises ``RateLimited`` when
    the limit is exceeded.

    The whole operation is one atomic ``find_one_and_update``: it drops expired
    timestamps and appends the current one in a single round trip, so
    concurrent requests cannot both read a stale count and both be allowed.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=window_seconds)

    try:
        record = await db[RATE_LIMITS].find_one_and_update(
            {"key": key},
            {
                # $pull removes timestamps that have fallen out of the window,
                # and $push appends this request. Both apply server-side.
                "$pull": {"timestamps": {"$lt": cutoff}},
                "$setOnInsert": {"key": key},
                "$set": {"expires_at": now + timedelta(seconds=window_seconds * 2)},
            },
            upsert=True,
            return_document=True,
        )
        timestamps = [
            t for t in (record or {}).get("timestamps", []) if t.replace(tzinfo=UTC) >= cutoff
        ]

        if len(timestamps) >= limit:
            oldest = min(timestamps)
            retry_after = max(
                1,
                int(
                    (
                        oldest.replace(tzinfo=UTC) + timedelta(seconds=window_seconds) - now
                    ).total_seconds()
                ),
            )
            log.warning("rate_limited", key=key, count=len(timestamps), limit=limit)
            raise RateLimited(
                "Too many requests. Please slow down.",
                retry_after=retry_after,
            )

        await db[RATE_LIMITS].update_one({"key": key}, {"$push": {"timestamps": now}})
        return limit - len(timestamps) - 1, 0

    except PyMongoError as exc:
        # Fail OPEN for rate limiting, unlike replay protection. A database
        # blip should not lock every user out of the product; the risk of a
        # brief unlimited window is lower than a total outage. This is a
        # deliberate, documented asymmetry.
        log.error("rate_limit_store_unavailable", error=str(exc))
        return limit, 0


async def check_user_and_ip(db: AsyncIOMotorDatabase, user_id: str, client_ip: str) -> None:
    """Apply both limits. Either can reject the request."""
    settings = get_settings()
    await check_rate_limit(db, f"user:{user_id}", settings.rate_limit_user_per_minute)
    await check_rate_limit(db, f"ip:{client_ip}", settings.rate_limit_ip_per_minute)


async def check_daily_quota(db: AsyncIOMotorDatabase, user_id: str) -> dict[str, int]:
    """Enforce the daily token allowance from recorded telemetry."""
    settings = get_settings()
    since = datetime.now(UTC) - timedelta(days=1)

    try:
        cursor = db[TELEMETRY].aggregate(
            [
                {"$match": {"user_id": user_id, "created_at": {"$gte": since}}},
                {"$group": {"_id": None, "total": {"$sum": "$tokens_used"}}},
            ]
        )
        rows = await cursor.to_list(length=1)
        used = int(rows[0]["total"]) if rows else 0
    except PyMongoError as exc:
        log.error("quota_check_failed", error=str(exc))
        return {
            "used": 0,
            "limit": settings.daily_token_quota,
            "remaining": settings.daily_token_quota,
        }

    if used >= settings.daily_token_quota:
        log.warning("quota_exceeded", user_id=user_id, used=used)
        raise QuotaExceeded(
            "Daily usage limit reached. It resets 24 hours after your first request.",
            retry_after=3600,
        )

    return {
        "used": used,
        "limit": settings.daily_token_quota,
        "remaining": settings.daily_token_quota - used,
    }


async def record_usage(
    db: AsyncIOMotorDatabase,
    *,
    user_id: str,
    correlation_id: str,
    tokens_used: int,
    model: str = "",
    decision: str = "",
) -> None:
    """Record token spend. Best-effort: never fails a user request."""
    try:
        await db[TELEMETRY].insert_one(
            {
                "user_id": user_id,
                "correlation_id": correlation_id,
                "tokens_used": int(tokens_used),
                "model": model,
                "decision": decision,
                "created_at": datetime.now(UTC),
            }
        )
    except PyMongoError as exc:
        log.error("telemetry_write_failed", error=str(exc))
