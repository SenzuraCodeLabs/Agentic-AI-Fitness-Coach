"""Agent 1 - Gatekeeper: trust, safety and NLU pipeline.

At P1 this only forwards to the coach so the four-service trace can be shown.
The nine-layer pipeline is added in P2 behind the same endpoint.
"""

from __future__ import annotations

from fastapi import Depends

from shared.contracts.client import AgentClient
from shared.contracts.enums import AgentName
from shared.contracts.envelope import Envelope
from shared.contracts.server import inbound_envelope, reply_envelope
from shared.logging import get_logger
from shared.service import create_service

log = get_logger("agent1_gatekeeper")

app = create_service(
    service_name="agent1_gatekeeper",
    title="FitCoach Agent 1 - Gatekeeper",
    ensure_indexes=True,
)


@app.post("/a2a/assess")
async def assess(
    envelope: Envelope = Depends(inbound_envelope(AgentName.GATEKEEPER)),
) -> dict:
    """Stub: forward to the coach and relay the reply."""
    log.info("assess_received", intent=str(envelope.intent))

    async with AgentClient(AgentName.GATEKEEPER) as client:
        coach_reply = await client.send(
            recipient=AgentName.COACH,
            path="/a2a/coach",
            payload=envelope.payload,
            trust=envelope.trust,
            inbound=envelope,
        )

    reply = reply_envelope(
        envelope,
        sender=AgentName.GATEKEEPER,
        payload=coach_reply.payload,
        trust=coach_reply.trust,
    )
    return reply.model_dump(mode="json")
