"""HMAC-SHA256 signing and verification of envelopes.

WHY CANONICALISATION IS REQUIRED
--------------------------------
An HMAC is computed over bytes, but an envelope is a JSON object, and one
object has many valid encodings: key order, whitespace, unicode escaping and
float formatting all vary between serialisers and language runtimes. If the
sender hashes ``{"a":1,"b":2}`` and the receiver re-serialises the parsed object
as ``{"b": 2, "a": 1}``, the digests differ and every legitimate message fails.

The naive fix, hashing the exact received byte string, is worse: it forces the
receiver to verify before parsing and validating, so it must trust unvalidated
input, and any proxy that reformats JSON silently breaks authentication.

So both sides agree on one deterministic encoding, computed from the *parsed*
object: sorted keys, no insignificant whitespace, UTF-8 without ASCII escaping,
and timestamps normalised to UTC ISO-8601 with a fixed precision. Identical
messages then produce identical bytes on any platform.

Canonicalisation is also a security control, not only an interoperability one.
Without a fixed encoding an attacker can look for two different documents with
the same canonical form, or exploit a parser that accepts duplicate keys, and
mount a signature-confusion attack. Sorting keys and forbidding unknown fields
removes that ambiguity.

WHY compare_digest AND NOT ==
-----------------------------
``==`` on strings returns as soon as it finds a differing byte, so how long the
comparison takes leaks how many leading bytes were correct. An attacker who can
time many requests recovers a valid signature byte by byte, needing roughly
256 x 64 attempts instead of 2**256. ``hmac.compare_digest`` compares in time
that does not depend on the position of the first difference, so timing reveals
nothing about the expected value.
"""

from __future__ import annotations

import hmac
import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from shared.contracts.enums import ALLOWED_ROUTES, AgentName
from shared.contracts.envelope import Envelope
from shared.errors import (
    EnvelopeExpired,
    SignatureInvalid,
    UnknownPeer,
)

# Bumping this changes the signed bytes, so it is part of the signature's
# domain. A verifier that supports several versions must select the matching
# canonicaliser rather than assuming the latest.
CANONICAL_FORM_VERSION = "1"

# Fields excluded from the signed bytes.
#   signature - a value cannot cover itself.
#   trace     - each hop appends to it, so it changes in transit by design; it
#               is re-signed by the appending agent rather than being immutable.
_UNSIGNED_FIELDS = frozenset({"signature", "trace"})


def _normalise(value: Any) -> Any:
    """Recursively convert a value to its canonical JSON representation.

    Datetimes become UTC ISO-8601 with microsecond precision and a literal
    ``Z``. Python's ``isoformat`` emits ``+00:00``; pinning one spelling means
    a receiver that reconstructs the string cannot disagree with the sender.
    """
    if isinstance(value, datetime):
        dt = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_normalise(v) for v in value]
    if isinstance(value, float):
        # Floats are the classic canonicalisation hazard: repr differs between
        # runtimes. Round to a fixed precision and collapse -0.0, well beyond
        # the precision any field here needs (risk scores, kilograms).
        rounded = round(value, 6)
        return 0.0 if rounded == 0 else rounded
    return value


def canonical_json(envelope: Envelope) -> bytes:
    """Return the exact bytes that are signed and verified.

    Both sides call this on a *parsed and validated* ``Envelope``, so the
    receiver never hashes unvalidated input.
    """
    data = envelope.model_dump(mode="python", exclude=set(_UNSIGNED_FIELDS))
    payload = {
        "_canonical_version": CANONICAL_FORM_VERSION,
        **_normalise(data),
    }
    return json.dumps(
        payload,
        sort_keys=True,  # key order cannot vary
        separators=(",", ":"),  # no insignificant whitespace
        ensure_ascii=False,  # one spelling for non-ASCII, encoded as UTF-8
        allow_nan=False,  # NaN/Infinity are not valid JSON
    ).encode("utf-8")


def compute_signature(envelope: Envelope, secret: str) -> str:
    """Return the hex HMAC-SHA256 over the envelope's canonical bytes."""
    return hmac.new(
        secret.encode("utf-8"),
        canonical_json(envelope),
        sha256,
    ).hexdigest()


def sign(envelope: Envelope, secret: str) -> Envelope:
    """Return a copy of the envelope carrying its signature."""
    # Signing a copy whose signature field is already None keeps the signed
    # bytes identical whether or not the input was previously signed.
    unsigned = envelope.model_copy(update={"signature": None})
    return unsigned.model_copy(update={"signature": compute_signature(unsigned, secret)})


def verify(
    envelope: Envelope,
    secret: str,
    *,
    expected_recipient: AgentName | None = None,
    clock_skew_seconds: int = 30,
    now: datetime | None = None,
) -> None:
    """Raise if the envelope is not a valid, fresh, correctly routed message.

    Checks run cheapest-first, but ordering is not a security property here:
    every failure maps to the same 401 family at the boundary, so an attacker
    cannot distinguish "expired" from "bad signature" by status code.

    Replay detection is deliberately absent: it needs a database round trip and
    lives in ``replay.py``, called by the server dependency after this returns.
    """
    now = now or datetime.now(UTC)

    # 1. Routing. Checked before cryptography because it needs no secret and
    #    enforces least privilege: holding the shared key must not grant the
    #    ability to talk to any service.
    if (envelope.sender, envelope.recipient) not in ALLOWED_ROUTES:
        raise UnknownPeer(
            f"route {envelope.sender} -> {envelope.recipient} is not permitted",
        )
    if expected_recipient is not None and envelope.recipient != expected_recipient:
        raise UnknownPeer("envelope is addressed to a different service")

    # 2. Freshness. expires_at bounds how long a captured envelope stays useful,
    #    which also bounds how long the nonce store must remember a message_id.
    if envelope.expires_at < now:
        raise EnvelopeExpired("envelope expired")

    # 3. Clock skew. A message issued in the future beyond tolerance suggests a
    #    forged timestamp or badly desynchronised clocks; accepting it would
    #    extend the replay window arbitrarily.
    skew = (envelope.issued_at - now).total_seconds()
    if skew > clock_skew_seconds:
        raise EnvelopeExpired("issued_at is too far in the future")

    # 4. Signature, last because it is the most expensive check.
    if not envelope.signature:
        raise SignatureInvalid("envelope is unsigned")

    expected = compute_signature(envelope, secret)
    if not hmac.compare_digest(expected, envelope.signature):
        raise SignatureInvalid("signature mismatch")


def verify_ok(envelope: Envelope, secret: str, **kwargs: Any) -> bool:
    """Boolean form of ``verify`` for tests and non-raising call sites."""
    try:
        verify(envelope, secret, **kwargs)
        return True
    except (SignatureInvalid, EnvelopeExpired, UnknownPeer):
        return False


def content_hash(envelope: Envelope) -> str:
    """Stable hash of an envelope's content, used by the audit hash chain."""
    return sha256(canonical_json(envelope)).hexdigest()
