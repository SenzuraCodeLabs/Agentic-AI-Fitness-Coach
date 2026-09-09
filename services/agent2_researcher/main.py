"""Agent 2 - Researcher.

Owned by a teammate. P1 protocol stub only: real retrieval runs over ChromaDB
behind this endpoint.
"""

from __future__ import annotations

from fastapi import Depends

from shared.contracts.enums import AgentName
from shared.contracts.envelope import Envelope, RetrievalPayload
from shared.contracts.server import inbound_envelope, reply_envelope
from shared.logging import get_logger
from shared.service import create_service

log = get_logger("agent2_researcher")

app = create_service(
    service_name="agent2_researcher",
    title="FitCoach Agent 2 - Researcher",
)


@app.post("/a2a/retrieve")
async def retrieve(
    envelope: Envelope = Depends(inbound_envelope(AgentName.RESEARCHER)),
) -> dict:
    """Stub retrieval returning one clearly labelled placeholder chunk."""
    log.info("retrieval_received", hops=len(envelope.trace))

    query = envelope.payload.query if isinstance(envelope.payload, RetrievalPayload) else ""
    reply = reply_envelope(
        envelope,
        sender=AgentName.RESEARCHER,
        payload=RetrievalPayload(
            query=query,
            chunks=[
                {
                    "source": "stub://not-implemented",
                    "text": "[stub retrieval - vector search not implemented]",
                    "score": 0.0,
                }
            ],
            raw_text_redacted=envelope.payload.raw_text_redacted,
        ),
        trust=envelope.trust,
    )
    return reply.model_dump(mode="json")
