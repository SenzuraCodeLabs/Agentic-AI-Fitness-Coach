# ADR 0001: Signed envelope for all inter-agent communication

**Status:** Accepted, 2026-09-09

## Context

One user turn crosses four processes. Downstream agents must know who sent a
message, that it was not modified, and what the Gatekeeper concluded about its
safety. Two of those services are owned by teammates.

## Decision

Every inter-agent message is a Pydantic `Envelope` signed with HMAC-SHA256 over
a canonical JSON encoding. The Gatekeeper's verdict travels inside the signed
region as a `trust` block.

## Alternatives considered

**Bearer token per service.** Authenticates the connection, not the message.
Anything terminating TLS could alter the body, including the risk score.

**mTLS only.** Same objection, plus certificate management that a coursework
deployment cannot justify.

**Asymmetric signatures (Ed25519).** Strictly better for containment: a
compromised service could not mint messages for others. Rejected for now
because key distribution across three developers' machines outweighs the
benefit at this scale. Recorded as the main residual risk in `docs/protocol.md`.

## Consequences

- Trust decisions cannot be forged or downgraded in transit.
- `shared/contracts/` becomes a frozen interface three people depend on.
- Every service pays one HMAC per hop, which is negligible next to a network
  round trip.
- A symmetric shared key means full compromise of one service is not contained.
