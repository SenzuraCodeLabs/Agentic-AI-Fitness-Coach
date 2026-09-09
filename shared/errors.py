"""Typed exceptions and the RFC 7807 problem+json model.

Every failure the system can produce is one of these types. The mapping from
exception to HTTP status lives on the exception class, so a handler raises a
domain error and never constructs a status code by hand.

Error bodies are deliberately terse. A verification failure says "envelope
rejected" and puts the specific reason in the server log under the correlation
ID, rather than telling a caller which of signature, expiry, or replay tripped.
Detailed failure reasons are an oracle an attacker can iterate against.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProblemDetail(BaseModel):
    """RFC 7807 problem detail body."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ProtocolError(Exception):
    """Base class for every error mapped to problem+json at the boundary."""

    problem_type = "about:blank#protocol-error"
    title = "Protocol error"
    status = 400

    def __init__(self, detail: str | None = None, **extra: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.extra = extra

    def to_problem(self) -> ProblemDetail:
        return ProblemDetail(
            type=self.problem_type,
            title=self.title,
            status=self.status,
            detail=self.detail,
            extra=self.extra,
        )


# --- Envelope / A2A protocol -----------------------------------------------


class EnvelopeRejected(ProtocolError):
    """Inbound envelope failed verification.

    One error type covers bad signature, expiry, skew, replay and unknown
    sender on purpose: the client learns the envelope was rejected, not which
    check failed.
    """

    problem_type = "about:blank#envelope-rejected"
    title = "Envelope rejected"
    status = 401


class SignatureInvalid(EnvelopeRejected):
    problem_type = "about:blank#signature-invalid"
    title = "Envelope signature invalid"


class EnvelopeExpired(EnvelopeRejected):
    problem_type = "about:blank#envelope-expired"
    title = "Envelope expired"


class ReplayDetected(EnvelopeRejected):
    problem_type = "about:blank#replay-detected"
    title = "Envelope replay detected"


class UnknownPeer(EnvelopeRejected):
    problem_type = "about:blank#unknown-peer"
    title = "Unknown sender or recipient"


class PayloadMismatch(ProtocolError):
    problem_type = "about:blank#payload-mismatch"
    title = "Payload does not match declared intent"
    status = 422


# --- Auth -------------------------------------------------------------------


class AuthError(ProtocolError):
    problem_type = "about:blank#unauthorized"
    title = "Authentication failed"
    status = 401


class ForbiddenError(ProtocolError):
    problem_type = "about:blank#forbidden"
    title = "Forbidden"
    status = 403


class EmailNotVerified(ProtocolError):
    problem_type = "about:blank#email-not-verified"
    title = "Email address not verified"
    status = 403


# --- Rate limiting ----------------------------------------------------------


class RateLimited(ProtocolError):
    problem_type = "about:blank#rate-limited"
    title = "Rate limit exceeded"
    status = 429

    def __init__(self, detail: str | None = None, retry_after: int = 60, **extra: Any) -> None:
        super().__init__(detail, **extra)
        self.retry_after = retry_after


class QuotaExceeded(RateLimited):
    problem_type = "about:blank#quota-exceeded"
    title = "Daily token quota exceeded"


# --- Pipeline / policy ------------------------------------------------------


class RequestBlocked(ProtocolError):
    """The policy engine refused the request.

    The detail is the neutral user-facing message chosen by the policy rule; it
    never names the detector that fired.
    """

    problem_type = "about:blank#request-blocked"
    title = "Request blocked by safety policy"
    status = 403


class UpstreamUnavailable(ProtocolError):
    problem_type = "about:blank#upstream-unavailable"
    title = "Upstream agent unavailable"
    status = 503


class ValidationFailure(ProtocolError):
    problem_type = "about:blank#validation-error"
    title = "Request validation failed"
    status = 422
