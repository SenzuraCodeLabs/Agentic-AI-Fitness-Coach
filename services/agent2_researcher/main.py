"""Agent 2 - Researcher: RAG retrieval over the evidence corpus."""

from __future__ import annotations

from fastapi import Depends

from services.agent2_researcher.retrieval import retrieve, warm_up
from shared.contracts.enums import AgentName
from shared.contracts.envelope import Envelope, RetrievalPayload
from shared.contracts.server import inbound_envelope, reply_envelope
from shared.logging import get_logger
from shared.service import create_service

log = get_logger("agent2_researcher")

app = create_service(
    service_name="agent2_researcher",
    title="FitCoach Agent 2 - Researcher",
    on_startup=warm_up,
)


@app.post("/a2a/retrieve")
async def retrieve_evidence(
    envelope: Envelope = Depends(inbound_envelope(AgentName.RESEARCHER)),
) -> dict:
    """Return evidence chunks relevant to the query, each with its source."""
    payload = envelope.payload
    query = payload.query if isinstance(payload, RetrievalPayload) else payload.raw_text_redacted
    top_k = payload.top_k if isinstance(payload, RetrievalPayload) else 4

    chunks = retrieve(query, top_k=top_k)
    log.info("retrieval_served", chunks=len(chunks), hops=len(envelope.trace))

    reply = reply_envelope(
        envelope,
        sender=AgentName.RESEARCHER,
        payload=RetrievalPayload(
            query=query[:2000],
            chunks=chunks,
            top_k=top_k,
            raw_text_redacted=payload.raw_text_redacted,
        ),
        trust=envelope.trust,
    )
    return reply.model_dump(mode="json")
