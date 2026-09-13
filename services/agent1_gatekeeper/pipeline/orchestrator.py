"""Pipeline orchestration: runs L1-L8 in order and returns a full decision trace.

ORDER IS A SECURITY PROPERTY, not an implementation detail. Each layer depends
on the previous one having run:

  L1 canonicalise  must precede everything, or later layers match on the
                   attacker's chosen encoding instead of the text.
  L2 deobfuscate   must precede L5, or an encoded payload is scored as noise.
  L3 lexicon       must precede L4, so extraction sees standardised terms.
  L4 extract       must precede L7, which conditions on extraction confidence.
  L5 threat        must precede L7, which conditions on risk score.
  L6 redact        MUST precede any external call. This is the invariant with
                   real consequences: once personal data reaches a third-party
                   API it is in their logs, and no later redaction undoes it.
  L7 policy        decides.
  L8 envelope      builds the signed outbound message and audit record.

SHORT-CIRCUITING. A terminal decision (BLOCK, REFUSE_MEDICAL, CLARIFY) stops
the pipeline: no downstream agent is called, so no API cost and no data
movement for a request that was refused.

THE L5/L6 ORDERING SUBTLETY. Threat scoring runs BEFORE redaction, on the
unredacted text, which looks like it contradicts the invariant. It does not:
L5's rule and semantic signals are local computation. Only the LLM judge leaves
the process, and it is called with text that has already been redacted, which
is why the judge receives ``redacted_for_judge`` rather than the raw input.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from services.agent1_gatekeeper.pipeline import (
    l1_canonicalise,
    l2_deobfuscate,
    l3_lexicon,
    l4_extractor,
    l5_threat_scorer,
    l6_pii_redactor,
    l7_policy_engine,
    l8_envelope,
)
from services.agent1_gatekeeper.pipeline.base import LayerTrace
from services.agent1_gatekeeper.pipeline.intent import classify_intent
from shared.config import get_settings
from shared.contracts.enums import AgentName, Decision, Intent, ReasonCode
from shared.contracts.envelope import Envelope, TrustMetadata
from shared.logging import get_correlation_id, get_logger

log = get_logger("orchestrator")

PIPELINE_VERSION = "pipeline-1.0"


@dataclass(slots=True)
class PipelineResult:
    decision: Decision
    intent: Intent
    risk_score: float
    reason_codes: list[ReasonCode]
    policy_rule_id: str
    user_message: str
    envelope: Envelope | None
    trust: TrustMetadata
    layer_traces: list[LayerTrace] = field(default_factory=list)
    redacted_text: str = ""
    extraction: Any = None
    total_ms: float = 0.0
    pii_vault: l6_pii_redactor.RedactionResult | None = None

    @property
    def is_terminal(self) -> bool:
        return self.decision in {Decision.BLOCK, Decision.REFUSE_MEDICAL, Decision.CLARIFY}

    def trace_dict(self) -> dict[str, Any]:
        """The full decision trace, for /api/explain and the transparency panel."""
        return {
            "pipeline_version": PIPELINE_VERSION,
            "decision": str(self.decision),
            "intent": str(self.intent),
            "risk_score": self.risk_score,
            "reason_codes": [str(c) for c in self.reason_codes],
            "policy_rule_id": self.policy_rule_id,
            "total_ms": round(self.total_ms, 3),
            "signal_contributions": self.trust.signal_contributions,
            "detector_versions": self.trust.detector_versions,
            "extraction_confidence": self.trust.extraction_confidence,
            "layers": [t.to_dict() for t in self.layer_traces],
        }

    def layer_timings(self) -> dict[str, float]:
        return {t.layer: t.duration_ms for t in self.layer_traces}


async def run_pipeline(
    text: str,
    *,
    timezone: str = "UTC",
    use_judge: bool | None = None,
    correlation_id: str | None = None,
) -> PipelineResult:
    """Run the full Gatekeeper pipeline over one user message."""
    started = time.perf_counter()
    if use_judge is None:
        use_judge = get_settings().llm_judge_enabled
    cid = correlation_id or get_correlation_id()
    traces: list[LayerTrace] = []
    reason_codes: list[ReasonCode] = []

    # --- L1: canonicalise --------------------------------------------------
    canonical = l1_canonicalise.canonicalise(text)
    traces.append(canonical.trace)
    reason_codes.extend(canonical.trace.reason_codes)

    # --- L2: deobfuscate ---------------------------------------------------
    decoded = l2_deobfuscate.deobfuscate(canonical.text)
    traces.append(decoded.trace)
    reason_codes.extend(decoded.trace.reason_codes)

    # --- L3: jargon expansion ---------------------------------------------
    lexicon = l3_lexicon.expand_jargon(canonical.text)
    traces.append(lexicon.trace)

    # --- Intent classification --------------------------------------------
    intent_result = classify_intent(lexicon.text, canonical.text)
    traces.append(intent_result.trace)
    reason_codes.extend(intent_result.trace.reason_codes)

    # --- L4: structured extraction ----------------------------------------
    extraction = l4_extractor.extract(lexicon.text, timezone=timezone)
    traces.append(extraction.trace)
    if intent_result.intent is Intent.LOG_WORKOUT:
        reason_codes.extend(extraction.trace.reason_codes)

    # --- L6 runs BEFORE the judge call inside L5 ---------------------------
    # Redaction is done here, ahead of L5, precisely so the judge never sees
    # personal data. The local signals still score the unredacted variants,
    # because an attacker could otherwise hide a payload inside something that
    # looks like PII.
    redaction = l6_pii_redactor.redact(canonical.text)
    traces.append(redaction.trace)
    reason_codes.extend(redaction.trace.reason_codes)

    # --- L5: threat assessment --------------------------------------------
    # Local signals see every variant; the judge sees only redacted text.
    local_variants = decoded.all_text()
    assessment = await l5_threat_scorer.assess_threat(
        [redaction.text, *local_variants[1:]] if use_judge else local_variants,
        use_judge=use_judge,
    )
    traces.append(assessment.trace)
    reason_codes.extend(assessment.reason_codes)

    # --- L7: policy --------------------------------------------------------
    policy = l7_policy_engine.decide(
        l7_policy_engine.PolicyInput(
            intent=intent_result.intent,
            risk_score=assessment.risk_score,
            reason_codes=reason_codes,
            extraction_confidence=(
                extraction.confidence if intent_result.intent is Intent.LOG_WORKOUT else None
            ),
            contains_pii=redaction.contains_pii,
        )
    )
    traces.append(policy.trace)

    # Deduplicate while preserving order: reason codes are evidence, and a
    # repeated code adds nothing.
    seen: dict[ReasonCode, None] = {}
    for code in reason_codes:
        if code is not ReasonCode.CLEAN:
            seen[code] = None
    ordered_codes = list(seen) or [ReasonCode.CLEAN]

    trust = TrustMetadata(
        risk_score=assessment.risk_score,
        decision=policy.decision,
        reason_codes=ordered_codes,
        detector_versions={**assessment.detector_versions, "pipeline": PIPELINE_VERSION},
        extraction_confidence=(
            extraction.confidence if intent_result.intent is Intent.LOG_WORKOUT else None
        ),
        policy_rule_id=policy.rule_id,
        signal_contributions=assessment.signal_contributions,
    )

    # --- L8: envelope, only when the turn continues -----------------------
    envelope: Envelope | None = None
    if policy.decision in {Decision.ALLOW, Decision.SANITISE}:
        payload = l8_envelope.build_payload(
            intent=intent_result.intent,
            decision=policy.decision,
            redacted_text=redaction.text,
            extraction=extraction,
            user_message=policy.user_message,
            missing_fields=extraction.missing_fields,
        )
        envelope = l8_envelope.build_envelope(
            payload=payload,
            trust=trust,
            correlation_id=cid,
            recipient=AgentName.COACH,
        )

    total_ms = (time.perf_counter() - started) * 1000

    log.info(
        "pipeline_complete",
        decision=str(policy.decision),
        intent=str(intent_result.intent),
        risk_score=assessment.risk_score,
        policy_rule=policy.rule_id,
        reason_codes=[str(c) for c in ordered_codes],
        total_ms=round(total_ms, 2),
        short_circuited=policy.decision
        in {Decision.BLOCK, Decision.REFUSE_MEDICAL, Decision.CLARIFY},
    )

    return PipelineResult(
        decision=policy.decision,
        intent=intent_result.intent,
        risk_score=assessment.risk_score,
        reason_codes=ordered_codes,
        policy_rule_id=policy.rule_id,
        user_message=policy.user_message,
        envelope=envelope,
        trust=trust,
        layer_traces=traces,
        redacted_text=redaction.text,
        extraction=extraction,
        total_ms=total_ms,
        pii_vault=redaction,
    )


def warm_up() -> None:
    """Pre-load every cached model and resource at service startup."""
    l1_canonicalise._load_confusables()
    l3_lexicon._automaton()
    l4_extractor._nlp()
    l5_threat_scorer.warm_up()
    l7_policy_engine._load_policy()
    log.info("pipeline_warm", version=PIPELINE_VERSION)
