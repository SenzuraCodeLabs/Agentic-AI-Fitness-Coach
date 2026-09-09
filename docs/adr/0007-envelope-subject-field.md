# ADR 0007: Add `subject` to the envelope header

**Status:** Accepted, 2026-09-09
**Breaking change:** yes. Envelope version 1.0 to 1.1.

## Context

`shared/contracts/` was frozen at P1. Building Agent 3 exposed a gap the
original design missed: no user identifier travels with a message, so the coach
cannot load the right training history. Without history it cannot detect a
stall or progress a lift across sessions, which is most of its purpose.

## Options considered

**Put the user id in the payload.** Rejected: it would have to be added to
every payload type, and it is header information, not message content. A
recipient should be able to read it without parsing the payload.

**Put it in `TrustMetadata`.** Rejected as semantically wrong. The trust block
records the Gatekeeper's safety verdict; identity is not a safety verdict.

**Leave it out.** Rejected: the coach would compute only from the single set in
the current message, so stall detection and cross-session progression could not
work at all.

## Decision

Add an optional `subject` field to the `Envelope` header, and bump
`ENVELOPE_VERSION` to 1.1.

## Why it must be inside the signed region

As an unsigned header, any caller could set `subject` to another user's id and
read their training history. That is a direct authorisation bypass, not a
theoretical one. Because it is covered by the HMAC, only a holder of the shared
secret can assert it.

`test_subject_is_covered_by_the_signature` is the regression guard: it signs an
envelope for `user-alice`, rewrites the subject to `user-bob`, and asserts that
verification fails.

## Consequences

- **Teammates must pull before their services will interoperate.** An envelope
  built with the new field will fail `extra="forbid"` validation on an old
  checkout, and one built without it produces a different canonical form.
- The field is optional, so service-to-service messages with no user context
  stay valid.
- `AgentClient.build` carries the subject forward from an inbound envelope
  automatically, so a relayed turn keeps it across every hop without each
  handler having to remember.
