"""API gateway: auth, rate limiting, SSE streaming.

At P1 this exposes a trace endpoint that pushes one signed envelope through the
whole chain. Authentication and the chat endpoint arrive in P2c.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from shared.contracts.client import AgentClient
from shared.contracts.enums import AgentName, Decision, Intent, ReasonCode
from shared.contracts.envelope import QueryPayload, TrustMetadata
from shared.logging import get_correlation_id, get_logger
from shared.service import create_service

log = get_logger("gateway")

app = create_service(
    service_name="gateway",
    title="FitCoach Gateway",
    ensure_indexes=True,
)


class TraceRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@app.post("/api/trace-demo")
async def trace_demo(body: TraceRequest) -> dict:
    """Push a signed envelope through gatekeeper -> coach -> researcher."""
    payload = QueryPayload(
        intent=Intent.PROGRAM_QUERY,
        question=body.message,
        raw_text_redacted=body.message,
    )
    trust = TrustMetadata(
        risk_score=0.0,
        decision=Decision.ALLOW,
        reason_codes=[ReasonCode.CLEAN],
        detector_versions={"stub": "p1"},
    )

    async with AgentClient(AgentName.GATEWAY) as client:
        reply = await client.send(
            recipient=AgentName.GATEKEEPER,
            path="/a2a/assess",
            payload=payload,
            trust=trust,
        )

    return {
        "correlation_id": get_correlation_id(),
        "hops": [h.agent for h in reply.trace],
        "reply": reply.payload.model_dump(mode="json"),
    }
