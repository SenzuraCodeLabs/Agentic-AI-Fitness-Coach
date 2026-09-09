"""Inbound side of the A2A protocol: a FastAPI dependency that verifies.

Usage in a handler:

    @app.post("/a2a/assess")
    async def assess(env: Envelope = Depends(inbound_envelope(AgentName.GATEKEEPER))):
        ...

The dependency reads the raw body itself rather than declaring an ``Envelope``
parameter, because FastAPI's normal parsing would return a 422 with field-level
detail before verification runs. That detail is an oracle: it tells an attacker
exactly how their forged envelope was malformed. Here every rejection returns
the same shape.

Order of operations, and why:
  1. size guard     - reject oversized bodies before allocating a parse
  2. parse/validate - so signature verification runs on a validated object,
                      never on raw attacker-controlled bytes
  3. verify         - routing, freshness, skew, signature
  4. replay check   - last, because it is the only step needing a database
                      round trip; doing it first would let an unauthenticated
                      caller fill the nonce collection, a cheap denial of
                      service against storage.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request

from shared.config import get_settings
from shared.contracts.enums import AgentName
from shared.contracts.envelope import Envelope
from shared.contracts.replay import ReplayGuard
from shared.contracts.signing import verify
from shared.errors import EnvelopeRejected, ReplayDetected
from shared.logging import get_logger

log = get_logger("a2a.server")

_MAX_ENVELOPE_BYTES = 128 * 1024


def inbound_envelope(
    expected_recipient: AgentName,
    *,
    guard: ReplayGuard | None = None,
) -> Callable[[Request], Awaitable[Envelope]]:
    """Build a dependency verifying envelopes addressed to ``expected_recipient``."""

    async def dependency(request: Request) -> Envelope:
        settings = get_settings()
        body = await request.body()

        if len(body) > _MAX_ENVELOPE_BYTES:
            raise EnvelopeRejected("envelope too large")

        try:
            envelope = Envelope.model_validate_json(body)
        except ValueError:
            # Deliberately no field detail: see the module docstring.
            log.warning("envelope_unparseable", size=len(body))
            raise EnvelopeRejected("envelope could not be parsed") from None

        verify(
            envelope,
            settings.agent_shared_secret.get_secret_value(),
            expected_recipient=expected_recipient,
            clock_skew_seconds=settings.clock_skew_tolerance_seconds,
        )

        replay_guard = guard or ReplayGuard()
        if await replay_guard.is_replay(
            envelope.message_id,
            expires_at=envelope.expires_at,
            sender=str(envelope.sender),
            correlation_id=envelope.correlation_id,
        ):
            raise ReplayDetected("envelope has already been processed")

        log.info(
            "envelope_accepted",
            message_id=envelope.message_id,
            sender=str(envelope.sender),
            intent=str(envelope.intent),
            risk_score=envelope.trust.risk_score,
            decision=str(envelope.trust.decision),
            hops=len(envelope.trace),
        )
        # Stash for handlers that need the trace or need to reply in kind.
        request.state.envelope = envelope
        return envelope

    return dependency


def reply_envelope(
    inbound: Envelope,
    *,
    sender: AgentName,
    payload: object,
    trust: object | None = None,
) -> Envelope:
    """Build a signed reply travelling back along the inbound edge.

    Reuses the inbound correlation ID so the whole turn stays one trace, and
    carries the accumulated hop list forward.
    """
    from shared.contracts.client import AgentClient

    client = AgentClient(sender)
    return client.build(
        recipient=inbound.sender,
        payload=payload,  # type: ignore[arg-type]
        trust=trust,  # type: ignore[arg-type]
        correlation_id=inbound.correlation_id,
        inbound=inbound,
        subject=inbound.subject,
    )
