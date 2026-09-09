"""Replay protection.

Uses the in-memory guard so these run without a database. The Mongo-backed
guard is exercised in the integration tests, where its unique-index atomicity
is the property under test.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from shared.contracts.replay import InMemoryReplayGuard


async def test_first_use_is_not_a_replay():
    guard = InMemoryReplayGuard()
    assert await guard.is_replay("msg-1") is False


async def test_second_use_of_the_same_id_is_a_replay():
    """A valid signature does not make a message fresh."""
    guard = InMemoryReplayGuard()
    await guard.is_replay("msg-1")
    assert await guard.is_replay("msg-1") is True


async def test_distinct_ids_are_independent():
    guard = InMemoryReplayGuard()
    assert await guard.is_replay("a") is False
    assert await guard.is_replay("b") is False


async def test_expired_nonce_is_forgotten():
    """The store stays bounded: records live only as long as the envelope."""
    guard = InMemoryReplayGuard()
    past = datetime.now(UTC) - timedelta(seconds=1)
    await guard.is_replay("short-lived", expires_at=past)
    # Already expired, so the entry is swept and the id is reusable. This is
    # safe only because verify() independently rejects the expired envelope.
    assert await guard.is_replay("short-lived") is False


async def test_concurrent_claims_yield_exactly_one_winner():
    """The check must be atomic under concurrency.

    A read-then-write implementation lets two concurrent copies both observe
    "unseen". Exactly one caller must win.
    """
    guard = InMemoryReplayGuard()
    results = await asyncio.gather(*(guard.is_replay("same-id") for _ in range(20)))
    assert results.count(False) == 1
    assert results.count(True) == 19


@pytest.mark.parametrize("message_id", ["", "x" * 500])
async def test_odd_ids_do_not_crash_the_guard(message_id):
    guard = InMemoryReplayGuard()
    assert await guard.is_replay(message_id) is False
