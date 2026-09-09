"""Outbound side of the A2A protocol.

``AgentClient`` is the only supported way to call another agent. Building the
envelope, signing it, appending the hop and propagating the correlation ID all
happen here, so a caller cannot accidentally send bare JSON, and rule 4 in
CLAUDE.md is enforced by construction rather than by review.
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

import httpx

from shared.config import get_settings
from shared.contracts.enums import AgentName, Decision, ReasonCode
from shared.contracts.envelope import Envelope, Payload, TrustMetadata
from shared.contracts.signing import sign
from shared.errors import EnvelopeRejected, ProtocolError, UpstreamUnavailable
from shared.logging import CORRELATION_ID_HEADER, get_correlation_id, get_logger

log = get_logger("a2a.client")

# Only these are retried. A 4xx is a deterministic rejection: retrying a bad
# signature or a blocked request just multiplies load. Note that even for these,
# a retry re-sends the SAME envelope, whose message_id the peer may already have
# consumed, so ``send`` mints a fresh envelope per attempt (see below).
_RETRYABLE_STATUS = frozenset({502, 503, 504})

AGENT_URL_ATTR = {
    AgentName.GATEWAY: "gateway_url",
    AgentName.GATEKEEPER: "agent1_url",
    AgentName.RESEARCHER: "agent2_url",
    AgentName.COACH: "agent3_url",
}


class AgentClient:
    """Signed-envelope HTTP client for one sending agent."""

    def __init__(
        self,
        sender: AgentName,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
        max_attempts: int = 3,
    ) -> None:
        self.sender = sender
        self.timeout = timeout
        self.max_attempts = max_attempts
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> AgentClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _base_url(self, recipient: AgentName) -> str:
        return getattr(get_settings(), AGENT_URL_ATTR[recipient]).rstrip("/")

    def build(
        self,
        *,
        recipient: AgentName,
        payload: Payload,
        trust: TrustMetadata | None = None,
        correlation_id: str | None = None,
        inbound: Envelope | None = None,
    ) -> Envelope:
        """Build and sign an envelope.

        When ``inbound`` is given, its trace is carried forward and this agent
        is appended as a hop, so the full path is visible at the far end.
        """
        from shared.contracts.envelope import Hop, _utcnow

        settings = get_settings()
        # Every sender records itself, including the originator. Without this
        # the first agent is missing from the path and the audit trail cannot
        # show where a turn entered the system.
        trace = list(inbound.trace) if inbound is not None else []
        trace.append(Hop(agent=self.sender, received_at=_utcnow()))

        envelope = Envelope.build(
            sender=self.sender,
            recipient=recipient,
            correlation_id=correlation_id or get_correlation_id(),
            payload=payload,
            trust=trust
            or TrustMetadata(
                risk_score=0.0,
                decision=Decision.ALLOW,
                reason_codes=[ReasonCode.CLEAN],
            ),
            ttl_seconds=settings.envelope_ttl_seconds,
            trace=trace,
        )
        return sign(envelope, settings.agent_shared_secret.get_secret_value())

    async def send(
        self,
        *,
        recipient: AgentName,
        path: str,
        payload: Payload,
        trust: TrustMetadata | None = None,
        correlation_id: str | None = None,
        inbound: Envelope | None = None,
    ) -> Envelope:
        """Send a signed envelope and return the peer's signed reply.

        Retries transient failures with exponential backoff plus full jitter.
        Jitter matters because without it every client retrying a recovering
        service fires simultaneously and knocks it over again; randomising the
        delay spreads the load.
        """
        url = f"{self._base_url(recipient)}{path}"
        cid = correlation_id or get_correlation_id()
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            # A fresh envelope per attempt. Reusing one would present a
            # message_id the peer may have already consumed, so a retry after a
            # timed-out but successful request would be rejected as a replay.
            envelope = self.build(
                recipient=recipient,
                payload=payload,
                trust=trust,
                correlation_id=cid,
                inbound=inbound,
            )
            try:
                response = await self.http.post(
                    url,
                    content=envelope.model_dump_json(),
                    headers={
                        "Content-Type": "application/json",
                        CORRELATION_ID_HEADER: cid,
                    },
                    timeout=self.timeout,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                log.warning(
                    "a2a_transport_error",
                    recipient=str(recipient),
                    attempt=attempt,
                    error=str(exc),
                )
            else:
                if response.status_code == 200:
                    return self._parse_reply(response)

                if response.status_code in {401, 403}:
                    # The peer rejected our envelope. Deterministic: do not retry.
                    raise EnvelopeRejected(
                        f"{recipient} rejected the envelope",
                        status=response.status_code,
                    )
                if response.status_code not in _RETRYABLE_STATUS:
                    raise ProtocolError(
                        f"{recipient} returned {response.status_code}",
                        status=response.status_code,
                    )
                last_error = UpstreamUnavailable(f"{recipient} returned {response.status_code}")
                log.warning(
                    "a2a_retryable_status",
                    recipient=str(recipient),
                    status=response.status_code,
                    attempt=attempt,
                )

            if attempt < self.max_attempts:
                backoff = min(2.0 ** (attempt - 1), 4.0)
                await asyncio.sleep(backoff * secrets.randbelow(1000) / 1000)

        raise UpstreamUnavailable(
            f"{recipient} unreachable after {self.max_attempts} attempts",
        ) from last_error

    def _parse_reply(self, response: httpx.Response) -> Envelope:
        """Validate and verify the peer's reply.

        A reply is an envelope too and gets the same treatment as an inbound
        request. Trusting a response because we initiated the call would leave
        the return path unauthenticated.
        """
        from shared.contracts.signing import verify

        settings = get_settings()
        try:
            reply = Envelope.model_validate_json(response.content)
        except ValueError as exc:
            raise ProtocolError("peer reply is not a valid envelope") from exc

        verify(
            reply,
            settings.agent_shared_secret.get_secret_value(),
            expected_recipient=self.sender,
            clock_skew_seconds=settings.clock_skew_tolerance_seconds,
        )
        return reply
