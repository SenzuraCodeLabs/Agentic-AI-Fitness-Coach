"""User-scoped, expiring answer cache. No workout or security decisions are cached."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo.errors import PyMongoError

from services.agent2_researcher.corpus import CORPUS
from services.agent3_coach.answers import normalise_question
from shared.db import get_db
from shared.logging import get_logger

log = get_logger("coach.cache")
VERSION = hashlib.sha256(json.dumps(CORPUS, sort_keys=True).encode()).hexdigest()


def cache_key(user_id: str, question: str) -> str:
    return hashlib.sha256(
        json.dumps([user_id, normalise_question(question), VERSION, "answers-v1"]).encode()
    ).hexdigest()


async def read_answer(user_id: str, question: str) -> dict[str, Any] | None:
    try:
        return await get_db()["answer_cache"].find_one(
            {
                "_id": cache_key(user_id, question),
                "user_id": user_id,
                "expires_at": {"$gt": datetime.now(UTC)},
            }
        )
    except PyMongoError:
        log.warning("answer_cache_unavailable")
        return None


async def save_answer(user_id: str, question: str, text: str, citations: list) -> None:
    try:
        await get_db()["answer_cache"].update_one(
            {"_id": cache_key(user_id, question)},
            {
                "$set": {
                    "user_id": user_id,
                    "text": text,
                    "citations": citations,
                    "expires_at": datetime.now(UTC) + timedelta(hours=24),
                }
            },
            upsert=True,
        )
    except PyMongoError:
        log.warning("answer_cache_write_failed")
