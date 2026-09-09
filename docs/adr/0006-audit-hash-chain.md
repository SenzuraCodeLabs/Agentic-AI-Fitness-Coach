# ADR 0006: Hash-chained audit log

**Status:** Accepted, 2026-09-09

## Context

Security decisions need an audit trail that an attacker with database access
cannot quietly rewrite. A plain collection of documents offers no such
guarantee: anyone who can write can also edit or delete.

## Decision

Each audit record stores a SHA-256 hash over its own canonical content chained
to the previous record's hash, plus a monotonic sequence number.

## Properties

Altering any record changes its content hash, which breaks the link every later
record depends on. Deleting one leaves a sequence gap. Both are detected by
`verify_chain()`, exposed as `scripts/verify_audit_chain.py`.

Verified by test: modifying a risk score in the middle of a five-record chain
is reported as "content hash mismatch at seq 2", and deleting a record is
reported as "sequence gap at seq 4".

## What is NOT stored

The user's message text. An audit log is a security record, and retaining
message content would make it a second copy of exactly what L6 redaction exists
to protect. Reason codes, the matched policy rule and per-layer timings are
enough to reconstruct why a decision was reached.

## Two MongoDB round-trip hazards

Both were found by running the verifier against real data, and both made the
chain appear broken on the very first record.

1. **Timezone.** BSON dates are stored as UTC and returned **naive**. Calling
   `astimezone(UTC)` on a naive datetime makes Python assume local time and
   shift it, so the digest computed before insert differed from the one
   computed after read by the local offset, 5h30m here.
2. **Precision.** BSON stores milliseconds; Python datetimes carry
   microseconds. Hashing microsecond precision produces a digest the database
   can never reproduce.

The canonicaliser now stamps naive values as UTC and truncates to
milliseconds, hashing only what actually survives storage.

## Limitations

This is tamper **evident**, not tamper **proof**. An attacker who can rewrite
the entire collection could recompute the whole chain. Preventing that requires
an external anchor, such as periodically publishing the head hash somewhere the
attacker does not control.

The chain head is read with a `find_one` sort. That is correct while the
Gatekeeper is the only writer. Multiple concurrent writers would need an atomic
counter via `find_one_and_update`.
