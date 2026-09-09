"""Agent 1 - Gatekeeper service.

The gateway runs the pipeline in-process for the chat endpoint, so this service
exposes the same capability over the A2A protocol for any caller that needs it,
and relays allowed turns to the coach.
"""

from __future__ import annotations

from fastapi import Depends

from services.agent1_gatekeeper.pipeline.orchestrator import run_pipeline, warm_up
from shared.contracts.client import AgentClient
from shared.contracts.enums import AgentName, Decision, Intent
from shared.contracts.envelope import Envelope, RefusalPayload
from shared.contracts.server import inbound_envelope, reply_envelope
from shared.logging import get_logger
from shared.service import create_service

log = get_logger("agent1_gatekeeper")

app = create_service(
    service_name="agent1_gatekeeper",
    title="FitCoach Agent 1 - Gatekeeper",
    ensure_indexes=True,
    # Loading spaCy, the embedding model and the automaton takes ~15s. Doing it
    # at boot means the first user request does not pay for it.
    on_startup=warm_up,
)


@app.post("/a2a/assess")
async def assess(
    envelope: Envelope = Depends(inbound_envelope(AgentName.GATEKEEPER)),
) -> dict:
    """Assess an inbound turn and relay it to the coach if policy allows.

    The gateway has usually already run the pipeline, so a payload arriving
    here with an ALLOW verdict is forwarded directly. Anything else is
    re-assessed: an envelope claiming to be safe is only as trustworthy as its
    signature, and re-running the pipeline costs ~15ms.
    """
    log.info(
        "assess_received",
        intent=str(envelope.intent),
        upstream_decision=str(envelope.trust.decision),
    )

    if envelope.trust.decision not in {Decision.ALLOW, Decision.SANITISE}:
        # A refused turn must never be relayed onward, whatever the caller says.
        result = await run_pipeline(
            envelope.payload.raw_text_redacted,
            correlation_id=envelope.correlation_id,
        )
        refusal = reply_envelope(
            envelope,
            sender=AgentName.GATEKEEPER,
            payload=RefusalPayload(
                intent=Intent.OUT_OF_SCOPE,
                user_message=result.user_message or "I cannot help with that request.",
                referral=False,
            ),
            trust=result.trust,
        )
        return refusal.model_dump(mode="json")

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


@app.post("/a2a/pipeline")
async def pipeline_only(
    envelope: Envelope = Depends(inbound_envelope(AgentName.GATEKEEPER)),
) -> dict:
    """Run the pipeline and return the decision trace without relaying.

    Used by the red-team harness, which needs the full per-layer output for a
    single input without triggering downstream calls or token spend.
    """
    result = await run_pipeline(
        envelope.payload.raw_text_redacted,
        correlation_id=envelope.correlation_id,
    )
    return {
        "decision": str(result.decision),
        "intent": str(result.intent),
        "risk_score": result.risk_score,
        "policy_rule_id": result.policy_rule_id,
        "user_message": result.user_message,
        "trace": result.trace_dict(),
    }
