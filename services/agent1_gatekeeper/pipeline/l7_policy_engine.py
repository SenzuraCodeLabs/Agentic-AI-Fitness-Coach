"""L7 - Declarative policy engine.

Turns the evidence gathered by L1-L6 into one decision. The matrix lives in
``policy_rules.yaml`` so the policy can be reviewed, diffed and argued about
without reading Python, which matters for a system whose safety behaviour has
to be defensible.

FIRST MATCH WINS, and the file's order encodes precedence. Medical safety is
placed above security deliberately: someone describing chest pain during bench
gets a referral even if their message also trips a threat rule. An injection
attempt is a system problem; an untreated cardiac event is not.

REFUSALS ARE NEUTRAL. The message shown to a blocked user never names the
detector that fired. Saying "blocked: ENCODED_PAYLOAD" hands an attacker a free
oracle: they iterate until the message changes. The reason codes travel
internally in the trust block instead, where the audit log and the explain
endpoint can use them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from services.agent1_gatekeeper.pipeline.base import LayerTrace, Timer
from shared.contracts.enums import Decision, Intent, ReasonCode
from shared.logging import get_logger

log = get_logger("l7_policy")

LAYER_VERSION = "l7-1.0"
RESOURCES = Path(__file__).resolve().parent.parent / "resources"


@dataclass(slots=True)
class PolicyInput:
    """Everything a policy rule may condition on."""

    intent: Intent
    risk_score: float
    reason_codes: list[ReasonCode] = field(default_factory=list)
    extraction_confidence: float | None = None
    contains_pii: bool = False


@dataclass(slots=True)
class PolicyDecision:
    decision: Decision
    rule_id: str
    user_message: str = ""
    referral: bool = False
    out_of_scope: bool = False
    trace: LayerTrace | None = None

    @property
    def is_terminal(self) -> bool:
        """True when the turn ends here and nothing is forwarded downstream."""
        return self.decision in {Decision.BLOCK, Decision.REFUSE_MEDICAL, Decision.CLARIFY}


@lru_cache(maxsize=1)
def _load_policy() -> tuple[list[dict[str, Any]], str]:
    path = RESOURCES / "policy_rules.yaml"
    if not path.exists():
        log.error("policy_rules_missing", path=str(path))
        return [], "0.0"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("rules", []), str(data.get("version", "0.0"))


def _matches(rule: dict[str, Any], candidate: PolicyInput) -> bool:
    """Every stated condition must hold. Absent conditions are wildcards."""
    when = rule.get("when") or {}

    expected_intent = when.get("intent")
    if expected_intent is not None and str(candidate.intent) != str(expected_intent):
        return False

    min_risk = when.get("min_risk_score")
    if min_risk is not None and candidate.risk_score < float(min_risk):
        return False

    max_risk = when.get("max_risk_score")
    if max_risk is not None and candidate.risk_score >= float(max_risk):
        return False

    required_codes = when.get("any_reason_code")
    if required_codes:
        present = {str(c) for c in candidate.reason_codes}
        if not present & {str(c) for c in required_codes}:
            return False

    max_confidence = when.get("max_extraction_confidence")
    if max_confidence is not None:
        # A rule keyed on confidence cannot fire when confidence is unknown:
        # treating "unknown" as "low" would send every non-log turn to CLARIFY.
        if candidate.extraction_confidence is None:
            return False
        if candidate.extraction_confidence >= float(max_confidence):
            return False

    return not (when.get("requires_pii") and not candidate.contains_pii)


def decide(candidate: PolicyInput) -> PolicyDecision:
    """Evaluate the ordered rule set and return the first match."""
    trace = LayerTrace(layer="L7_policy_engine", version=LAYER_VERSION)
    rules, version = _load_policy()

    with Timer(trace):
        matched: dict[str, Any] | None = None
        evaluated: list[str] = []
        for rule in rules:
            evaluated.append(str(rule.get("id", "?")))
            if _matches(rule, candidate):
                matched = rule
                break

    if matched is None:
        # No rule matched, including the default. That means the policy file is
        # broken, so fail closed rather than allowing the turn through.
        log.error("policy_no_match", intent=str(candidate.intent))
        trace.notes = {"error": "no rule matched", "rules_version": version}
        return PolicyDecision(
            decision=Decision.BLOCK,
            rule_id="FAIL-CLOSED",
            user_message=("I cannot process that request right now. Please try rephrasing it."),
            trace=trace,
        )

    decision = Decision(str(matched["decision"]))
    message = " ".join(str(matched.get("user_message", "")).split())

    trace.notes = {
        "matched_rule": matched.get("id"),
        "decision": str(decision),
        "rules_evaluated": len(evaluated),
        "rules_version": version,
        "inputs": {
            "intent": str(candidate.intent),
            "risk_score": candidate.risk_score,
            "extraction_confidence": candidate.extraction_confidence,
            "reason_codes": [str(c) for c in candidate.reason_codes],
        },
    }

    log.info(
        "policy_decision",
        rule_id=matched.get("id"),
        decision=str(decision),
        risk_score=candidate.risk_score,
        intent=str(candidate.intent),
    )

    return PolicyDecision(
        decision=decision,
        rule_id=str(matched.get("id", "?")),
        user_message=message,
        referral=bool(matched.get("referral", False)),
        out_of_scope=bool(matched.get("out_of_scope", False)),
        trace=trace,
    )
