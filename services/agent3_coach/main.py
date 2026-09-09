"""Agent 3 - Coach.

Owned by a teammate. This file carries only the P1 protocol stub so the
end-to-end trace can be demonstrated; the overload mathematics and telemetry
are theirs to implement behind this same endpoint.
"""

from __future__ import annotations

from fastapi import Depends

from shared.contracts.client import AgentClient
from shared.contracts.enums import AgentName, Intent
from shared.contracts.envelope import (
    CoachReplyPayload,
    Envelope,
    RetrievalPayload,
)
from shared.contracts.server import inbound_envelope, reply_envelope
from shared.logging import get_logger
from shared.service import create_service

log = get_logger("agent3_coach")

app = create_service(
    service_name="agent3_coach",
    title="FitCoach Agent 3 - Coach",
)


@app.post("/a2a/coach")
async def coach(
    envelope: Envelope = Depends(inbound_envelope(AgentName.COACH)),
) -> dict:
    """Stub: consult the researcher, then reply.

    Demonstrates that a single correlation ID spans gateway, gatekeeper, coach
    and researcher.
    """
    log.info("coach_received", intent=str(envelope.intent), hops=len(envelope.trace))

    citations: list[dict[str, str]] = []
    async with AgentClient(AgentName.COACH) as client:
        retrieval = RetrievalPayload(
            query=envelope.payload.raw_text_redacted[:2000] or "progressive overload",
            raw_text_redacted=envelope.payload.raw_text_redacted,
        )
        research_reply = await client.send(
            recipient=AgentName.RESEARCHER,
            path="/a2a/retrieve",
            payload=retrieval,
            trust=envelope.trust,
            inbound=envelope,
        )
        if isinstance(research_reply.payload, RetrievalPayload):
            citations = [
                {"source": str(c.get("source", "")), "snippet": str(c.get("text", ""))[:200]}
                for c in research_reply.payload.chunks
            ]

    reply = reply_envelope(
        envelope,
        sender=AgentName.COACH,
        payload=CoachReplyPayload(
            intent=Intent.PROGRAM_QUERY,
            reply_text="[stub coach reply - overload maths not implemented]",
            recommendation={},
            citations=citations,
            raw_text_redacted=envelope.payload.raw_text_redacted,
        ),
        trust=envelope.trust,
    )
    return reply.model_dump(mode="json")
