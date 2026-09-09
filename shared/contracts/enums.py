"""Closed vocabularies shared by every service.

These are ``str`` enums so they serialise to readable JSON and can be compared
against raw strings from Mongo without conversion, while still failing
validation on an unknown value. A closed vocabulary matters at a trust
boundary: a typo in a reason code should be a validation error at the edge, not
a policy rule that silently never matches.
"""

from __future__ import annotations

from enum import StrEnum


class Intent(StrEnum):
    """What the user is trying to do. Chosen by the Gatekeeper's classifier."""

    LOG_WORKOUT = "LOG_WORKOUT"
    EXERCISE_FORM = "EXERCISE_FORM"
    PROGRAM_QUERY = "PROGRAM_QUERY"
    PROGRESS_QUERY = "PROGRESS_QUERY"
    SMALL_TALK = "SMALL_TALK"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    MEDICAL_CONCERN = "MEDICAL_CONCERN"
    UNKNOWN = "UNKNOWN"


class Decision(StrEnum):
    """The policy engine's verdict on a turn.

    ALLOW          forward unchanged
    SANITISE       forward, but only the redacted and delimited text
    CLARIFY        do not guess; ask the user one targeted question
    REFUSE_MEDICAL refer to a professional, never give training advice
    BLOCK          neutral refusal, no detail about which detector fired
    """

    ALLOW = "ALLOW"
    SANITISE = "SANITISE"
    CLARIFY = "CLARIFY"
    REFUSE_MEDICAL = "REFUSE_MEDICAL"
    BLOCK = "BLOCK"


class ReasonCode(StrEnum):
    """Why a decision was reached.

    Reason codes are the audit trail and the evaluation labels. They are
    internal: they appear in logs, the explain endpoint and the transparency
    panel, but never in a refusal message shown to a blocked user, because
    naming the detector that fired tells an attacker what to evade.
    """

    # --- Injection and jailbreak families (L5 rules) --------------------
    INSTRUCTION_OVERRIDE = "INSTRUCTION_OVERRIDE"
    ROLE_PLAY_FRAMING = "ROLE_PLAY_FRAMING"
    SYSTEM_PROMPT_PROBE = "SYSTEM_PROMPT_PROBE"
    DELIMITER_INJECTION = "DELIMITER_INJECTION"
    ENCODED_PAYLOAD = "ENCODED_PAYLOAD"
    OBFUSCATED_TEXT = "OBFUSCATED_TEXT"
    TOOL_ABUSE = "TOOL_ABUSE"
    EXFILTRATION_ATTEMPT = "EXFILTRATION_ATTEMPT"
    SEMANTIC_ATTACK_MATCH = "SEMANTIC_ATTACK_MATCH"
    JUDGE_FLAGGED = "JUDGE_FLAGGED"

    # --- Privacy ---------------------------------------------------------
    PII_DETECTED = "PII_DETECTED"
    PII_REDACTED = "PII_REDACTED"

    # --- Safety ----------------------------------------------------------
    MEDICAL_ACUTE = "MEDICAL_ACUTE"
    MEDICAL_CHRONIC = "MEDICAL_CHRONIC"
    DISORDERED_EATING = "DISORDERED_EATING"
    MINOR_SAFEGUARDING = "MINOR_SAFEGUARDING"

    # --- Scope and quality ----------------------------------------------
    OUT_OF_DOMAIN = "OUT_OF_DOMAIN"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    AMBIGUOUS_EXERCISE = "AMBIGUOUS_EXERCISE"
    IMPLAUSIBLE_VALUE = "IMPLAUSIBLE_VALUE"

    # --- Traffic control -------------------------------------------------
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"

    # --- Protocol --------------------------------------------------------
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    ENVELOPE_EXPIRED = "ENVELOPE_EXPIRED"
    REPLAY_DETECTED = "REPLAY_DETECTED"
    UNKNOWN_PEER = "UNKNOWN_PEER"

    # --- Clean -----------------------------------------------------------
    CLEAN = "CLEAN"


class AgentName(StrEnum):
    """Valid envelope senders and recipients.

    An enum rather than a free string so an envelope claiming to come from an
    unrecognised service fails validation before any signature work.
    """

    GATEWAY = "gateway"
    GATEKEEPER = "agent1_gatekeeper"
    RESEARCHER = "agent2_researcher"
    COACH = "agent3_coach"


# Which agent may send to which. An envelope whose (sender, recipient) pair is
# absent here is rejected even with a valid signature: possession of the shared
# HMAC key must not let a compromised service address any peer it likes. This
# is the protocol's least-privilege control.
ALLOWED_ROUTES: frozenset[tuple[AgentName, AgentName]] = frozenset(
    {
        (AgentName.GATEWAY, AgentName.GATEKEEPER),
        (AgentName.GATEKEEPER, AgentName.COACH),
        (AgentName.COACH, AgentName.RESEARCHER),
        # Replies travel the same edges in reverse.
        (AgentName.GATEKEEPER, AgentName.GATEWAY),
        (AgentName.COACH, AgentName.GATEKEEPER),
        (AgentName.RESEARCHER, AgentName.COACH),
    }
)


class DecisionSeverity(StrEnum):
    """Coarse severity used by the audit log and the red-team risk matrix."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
