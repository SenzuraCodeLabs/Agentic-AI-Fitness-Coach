# ADR 0002: Discriminate the payload union on `kind`, not `intent`

**Status:** Accepted, 2026-09-09

## Context

The original design discriminated the payload union on `intent`. This fails at
import time: `PROGRAM_QUERY` is the intent of both the question sent to the
coach and the reply sent back, and `EXERCISE_FORM` of both a user question and
a retrieval result. Pydantic rejects a discriminator mapping one value to
several models.

## Decision

Add an explicit `kind` field (`WORKOUT_LOG`, `QUERY`, `CLARIFY`, `REFUSAL`,
`COACH_REPLY`, `RETRIEVAL`) and discriminate on it. Keep `intent` as semantic
metadata, and validate in `Envelope` that the payload's intent matches the
header's.

## Rationale

The two fields answer different questions. `intent` is "what does the user
want", which is domain semantics and legitimately repeats across message types.
`kind` is "what shape is this message", which is what a parser needs.
Conflating them made a modelling error look like a library limitation.

## Consequences

- The union parses unambiguously.
- A payload still cannot misrepresent itself: `kind` fixes the schema and the
  envelope validator ties intent to the header.
- One extra field on the wire, and one extra concept in the protocol doc.
