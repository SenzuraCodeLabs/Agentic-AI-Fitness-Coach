"""The signed message envelope exchanged between agents.

Design in one paragraph. Every inter-agent message is an ``Envelope``: a fixed
header carrying identity, timing and routing, a ``trust`` block recording what
the Gatekeeper concluded, a typed ``payload`` discriminated on ``kind``, and
a detached HMAC ``signature`` over everything else. The header exists so a
recipient can make an authorisation decision without parsing the payload, and
the trust block travels with the message so a downstream agent never has to
re-derive risk or take the user's text on trust.

Why the trust block is inside the signed region: if risk_score were a plain
header a compromised or spoofed caller could set it to zero. Because it is
covered by the signature, only a holder of the shared secret can assert it, and
the ``trace`` shows which agent did.

Threat model this addresses, in short: message forgery (signature),
modification in transit (signature over canonical bytes), replay (message_id
plus TTL), delayed replay after capture (expires_at), lateral movement between
services (ALLOWED_ROUTES), and prompt injection carried in user text
(the payload keeps user text in a dedicated redacted field that downstream
prompts wrap in spotlight delimiters).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.contracts.enums import AgentName, Decision, Intent, ReasonCode

ENVELOPE_VERSION = "1.1"

# Spotlighting delimiters. Any residual free text handed to an LLM is wrapped in
# these, with an instruction that content between them is data. The random-ish
# tag makes it costly for an attacker to close the block from inside the text,
# which is the standard weakness of a fixed delimiter such as triple backticks.
SPOTLIGHT_OPEN = "<<<FITCOACH_USER_DATA_7f3a>>>"
SPOTLIGHT_CLOSE = "<<<END_FITCOACH_USER_DATA_7f3a>>>"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def new_message_id() -> str:
    return uuid.uuid4().hex


class Hop(BaseModel):
    """One entry in the routing history.

    Each agent appends a hop before forwarding, giving an auditable path for a
    turn. A loop or an unexpected path is then visible in the audit record.
    """

    model_config = ConfigDict(extra="forbid")

    agent: AgentName
    received_at: datetime
    latency_ms: float | None = None
    note: str | None = Field(default=None, max_length=200)


class TrustMetadata(BaseModel):
    """The Gatekeeper's verdict, carried with the message.

    ``detector_versions`` is recorded so a benchmark result can be attributed to
    a specific detector build. Without it, a regression is untraceable: the
    evaluation would say recall changed but not what changed.
    """

    model_config = ConfigDict(extra="forbid")

    risk_score: float = Field(ge=0.0, le=1.0)
    decision: Decision
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    detector_versions: dict[str, str] = Field(default_factory=dict)
    extraction_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    policy_rule_id: str | None = None
    # Per-signal contributions from L5, kept for the explainability panel and
    # the individual report's analysis of why an attack was caught or missed.
    signal_contributions: dict[str, float] = Field(default_factory=dict)

    @field_validator("reason_codes")
    @classmethod
    def _dedupe(cls, v: list[ReasonCode]) -> list[ReasonCode]:
        seen: dict[ReasonCode, None] = {}
        for code in v:
            seen[code] = None
        return list(seen)


# --- Payloads ---------------------------------------------------------------
# The union below is discriminated on ``kind``, not on ``intent``.
#
# Intent answers "what does the user want" and legitimately repeats across
# message types: a PROGRAM_QUERY is the intent of both the question travelling
# to the coach and the reply travelling back. Kind answers "what shape is this
# message", which is what the parser actually needs to select a model. Using
# intent as the discriminator is ambiguous and Pydantic rejects it outright.
#
# Keeping both fields means a payload still cannot misrepresent itself: kind
# fixes the schema, and ``Envelope`` separately validates that the payload's
# intent matches the header's, so "LOG_WORKOUT carrying a free-text query"
# remains impossible.


class PayloadKind(StrEnum):
    """Message shape. The discriminator for the payload union."""

    WORKOUT_LOG = "WORKOUT_LOG"
    QUERY = "QUERY"
    CLARIFY = "CLARIFY"
    REFUSAL = "REFUSAL"
    COACH_REPLY = "COACH_REPLY"
    RETRIEVAL = "RETRIEVAL"


class BasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Redacted, canonicalised user text. Named to make the invariant obvious at
    # every call site: raw text must never be placed here.
    raw_text_redacted: str = Field(default="", max_length=4000)

    def spotlighted(self) -> str:
        """Return the user text wrapped in spotlight delimiters."""
        return f"{SPOTLIGHT_OPEN}\n{self.raw_text_redacted}\n{SPOTLIGHT_CLOSE}"


class WorkoutSet(BaseModel):
    """One exercise's prescription within a logged session."""

    model_config = ConfigDict(extra="forbid")

    exercise: str = Field(min_length=1, max_length=80)
    load_kg: float | None = Field(default=None, ge=0, le=1000)
    unit_original: Literal["kg", "lb", "bodyweight", "unknown"] = "unknown"
    reps: int | None = Field(default=None, ge=1, le=1000)
    sets: int | None = Field(default=None, ge=1, le=100)
    rpe: float | None = Field(default=None, ge=1, le=10)
    rir: int | None = Field(default=None, ge=0, le=10)

    @model_validator(mode="after")
    def _plausible(self) -> WorkoutSet:
        """Reject physiologically implausible combinations.

        Not a safety control, a data-quality one: a mistyped 5000 kg squat
        would otherwise poison the progressive-overload calculation for that
        user permanently.
        """
        if self.load_kg is not None and self.load_kg > 600:
            raise ValueError("load exceeds plausible human range")
        return self


class WorkoutLogPayload(BasePayload):
    kind: Literal[PayloadKind.WORKOUT_LOG] = PayloadKind.WORKOUT_LOG
    intent: Literal[Intent.LOG_WORKOUT] = Intent.LOG_WORKOUT
    sets_logged: list[WorkoutSet] = Field(min_length=1, max_length=40)
    session_date: datetime
    timezone: str = "UTC"
    notes: str | None = Field(default=None, max_length=500)


class QueryPayload(BasePayload):
    """A question to answer: form, programming, or progress."""

    kind: Literal[PayloadKind.QUERY] = PayloadKind.QUERY
    intent: Literal[
        Intent.EXERCISE_FORM,
        Intent.PROGRAM_QUERY,
        Intent.PROGRESS_QUERY,
        Intent.SMALL_TALK,
    ]
    question: str = Field(min_length=1, max_length=4000)
    entities: dict[str, list[str]] = Field(default_factory=dict)


class ClarifyPayload(BasePayload):
    kind: Literal[PayloadKind.CLARIFY] = PayloadKind.CLARIFY
    intent: Literal[Intent.UNKNOWN] = Intent.UNKNOWN
    question_to_user: str = Field(max_length=300)
    missing_fields: list[str] = Field(default_factory=list)


class RefusalPayload(BasePayload):
    """A terminal refusal: medical, out of scope, or blocked.

    ``user_message`` is the neutral text shown to the user. The reason lives in
    the trust block, not here, so the refusal itself reveals nothing about the
    detector.
    """

    kind: Literal[PayloadKind.REFUSAL] = PayloadKind.REFUSAL
    intent: Literal[Intent.MEDICAL_CONCERN, Intent.OUT_OF_SCOPE]
    user_message: str = Field(max_length=1000)
    referral: bool = False


class CoachReplyPayload(BasePayload):
    """Agent 3's answer travelling back toward the gateway."""

    kind: Literal[PayloadKind.COACH_REPLY] = PayloadKind.COACH_REPLY
    intent: Literal[Intent.PROGRAM_QUERY] = Intent.PROGRAM_QUERY
    reply_text: str = Field(max_length=8000)
    recommendation: dict[str, Any] = Field(default_factory=dict)
    citations: list[dict[str, str]] = Field(default_factory=list)
    tokens_used: int = 0


class RetrievalPayload(BasePayload):
    """Agent 2's retrieved evidence."""

    kind: Literal[PayloadKind.RETRIEVAL] = PayloadKind.RETRIEVAL
    intent: Literal[Intent.EXERCISE_FORM] = Intent.EXERCISE_FORM
    query: str = Field(max_length=2000)
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=50)


Payload = Annotated[
    WorkoutLogPayload
    | QueryPayload
    | ClarifyPayload
    | RefusalPayload
    | CoachReplyPayload
    | RetrievalPayload,
    Field(discriminator="kind"),
]


class Envelope(BaseModel):
    """A signed inter-agent message.

    ``extra="forbid"`` is essential rather than cosmetic: an unknown field would
    be dropped during parsing but still present in the bytes a naive verifier
    hashed, which is how signature-bypass bugs arise. Forbidding extras means
    the parsed object and the signed bytes describe the same message.
    """

    model_config = ConfigDict(extra="forbid")

    envelope_version: str = ENVELOPE_VERSION
    message_id: str = Field(default_factory=new_message_id, min_length=8, max_length=64)
    correlation_id: str = Field(min_length=1, max_length=64)
    trace: list[Hop] = Field(default_factory=list, max_length=16)

    sender: AgentName
    recipient: AgentName

    # Whose turn this is. Added in envelope version 1.1: without it a
    # downstream agent cannot load the right training history, so the coach
    # could not detect a stall or progress across sessions.
    #
    # It sits in the SIGNED region deliberately. As an unsigned header any
    # caller could set it to another user's id and read their history, which
    # would be a direct authorisation bypass. Covered by the signature, only a
    # holder of the shared secret can assert it.
    #
    # Optional so that service-to-service messages with no user context remain
    # valid.
    subject: str | None = Field(default=None, max_length=64)

    issued_at: datetime
    expires_at: datetime

    intent: Intent
    trust: TrustMetadata
    payload: Payload

    # Detached: excluded from the bytes that are hashed. See signing.py.
    signature: str | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> Envelope:
        # The header intent and the payload intent must agree. They are
        # separate fields because the header must be readable without payload
        # validation, and a mismatch would otherwise let a caller advertise a
        # benign intent while shipping a different payload.
        if self.payload.intent != self.intent:
            raise ValueError(
                f"header intent {self.intent} does not match payload intent {self.payload.intent}"
            )
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if self.sender == self.recipient:
            raise ValueError("sender and recipient must differ")
        return self

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _require_tz(cls, v: datetime) -> datetime:
        """Force timezone-aware UTC.

        A naive datetime compares ambiguously against ``now``, which would make
        expiry checks depend on the server's local timezone. Normalising here
        keeps the canonical form identical on both sides of the wire.
        """
        if v.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return v.astimezone(UTC)

    @classmethod
    def build(
        cls,
        *,
        sender: AgentName,
        recipient: AgentName,
        correlation_id: str,
        payload: Payload,
        trust: TrustMetadata,
        ttl_seconds: int = 120,
        trace: list[Hop] | None = None,
        subject: str | None = None,
    ) -> Envelope:
        """Construct an unsigned envelope with consistent timing fields."""
        now = _utcnow()
        return cls(
            message_id=new_message_id(),
            correlation_id=correlation_id,
            trace=trace or [],
            sender=sender,
            recipient=recipient,
            subject=subject,
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            intent=payload.intent,
            trust=trust,
            payload=payload,
        )

    def with_hop(self, agent: AgentName, latency_ms: float | None = None) -> Envelope:
        """Return a copy with one more hop appended.

        Returns a copy rather than mutating because any change invalidates the
        signature; the caller must re-sign, and an immutable style makes that
        hard to forget.
        """
        hop = Hop(agent=agent, received_at=_utcnow(), latency_ms=latency_ms)
        return self.model_copy(update={"trace": [*self.trace, hop], "signature": None})
