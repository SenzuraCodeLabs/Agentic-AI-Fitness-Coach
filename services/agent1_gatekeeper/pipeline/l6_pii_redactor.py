"""L6 - PII detection and redaction.

Purpose: remove personal data from text BEFORE it leaves this process for the
DeepSeek API or the vector store.

THE ORDERING INVARIANT
----------------------
Redaction must happen before any external call. Once a phone number reaches a
third-party API it is in their logs, and no later redaction undoes that. The
orchestrator enforces the order and ``test_redaction_precedes_external_call``
asserts it, because an ordering bug here is silent: everything still works,
data just leaks.

WHY A REVERSIBLE VAULT
----------------------
Placeholders are stable per request (``<EMAIL_1>``), and the mapping is kept in
memory scoped to the request so a reply mentioning ``<EMAIL_1>`` can be
rehydrated for the user. The vault never leaves the process and is never
persisted: writing it to Mongo would recreate exactly the exposure redaction
exists to prevent.

WHY LUHN FOR CARD NUMBERS
-------------------------
Any 16-digit run matches a naive card regex, and gym text is full of digit
runs: dates, weights, phone numbers, workout codes. The Luhn checksum is the
card-numbering standard's own integrity check, so requiring it cuts false
positives sharply at negligible cost. A wrongly redacted number would corrupt
a workout log.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.agent1_gatekeeper.pipeline.base import LayerTrace, Timer, Transformation
from shared.contracts.enums import ReasonCode

LAYER_VERSION = "l6-1.0"


# --- Patterns ---------------------------------------------------------------

_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
)

# International phone numbers. Requires either a leading + or a separator-rich
# shape, so a bare run of digits (a weight, a date) is not matched.
_PHONE = re.compile(
    r"(?<![\w.])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?\d{2,4}[\s.-]\d{3,4}[\s.-]?\d{3,4}(?![\w.])"
    r"|(?<![\w.])\+\d{9,15}(?![\w.])"
)

# Sri Lankan National Identity Card.
#   old format: 9 digits followed by V or X (e.g. 921234567V)
#   new format: 12 digits (e.g. 199212345678)
_NIC_OLD = re.compile(r"\b\d{9}[VvXx]\b")
_NIC_NEW = re.compile(r"\b(?:19|20)\d{10}\b")

# Passport numbers: one or two letters then 6-8 digits. Deliberately narrow;
# a broader pattern would swallow ordinary alphanumeric tokens.
_PASSPORT = re.compile(r"\b[A-Z]{1,2}\d{6,8}\b")

# Card-like runs of 13-19 digits, optionally separated. Validated with Luhn
# before being treated as a card.
#
# The final digit is matched separately so a trailing separator is not
# swallowed: "(?:\d[ -]?){13,19}" consumes the space after the last digit,
# which then vanishes from the redacted text ("<CARD_1>for the subscription").
_CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


@dataclass(slots=True)
class PiiFinding:
    kind: str
    placeholder: str
    original: str
    start: int
    end: int


@dataclass(slots=True)
class RedactionResult:
    text: str
    original: str
    findings: list[PiiFinding] = field(default_factory=list)
    trace: LayerTrace | None = None

    @property
    def contains_pii(self) -> bool:
        return bool(self.findings)

    def rehydrate(self, text: str) -> str:
        """Restore original values in a downstream reply.

        Used only on text being returned to the user who supplied the data, so
        it cannot disclose one user's PII to another.
        """
        for finding in self.findings:
            text = text.replace(finding.placeholder, finding.original)
        return text


def luhn_valid(digits: str) -> bool:
    """Luhn (mod 10) checksum, the card-numbering standard's integrity check.

    Double every second digit from the right; subtract 9 from any result above
    9; the total must be divisible by 10. Roughly 90% of random digit strings
    fail, which is why this is worth doing.
    """
    cleaned = [int(c) for c in digits if c.isdigit()]
    if len(cleaned) < 13:
        return False
    total = 0
    for index, digit in enumerate(reversed(cleaned)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _nic_old_valid(candidate: str) -> bool:
    """Sanity-check the old-format NIC's embedded day-of-year.

    Digits 3-5 encode day of year, with 500 added for women, so the value must
    fall in 1-366 or 501-866. This rejects arbitrary 9-digit runs.
    """
    try:
        day = int(candidate[2:5])
    except ValueError:
        return False
    return 1 <= day <= 366 or 501 <= day <= 866


def redact(text: str) -> RedactionResult:
    """Replace personal data with stable placeholders."""
    trace = LayerTrace(layer="L6_pii_redactor", version=LAYER_VERSION)
    findings: list[PiiFinding] = []
    original = text

    with Timer(trace):
        counters: dict[str, int] = {}

        def claim(kind: str) -> str:
            counters[kind] = counters.get(kind, 0) + 1
            return f"<{kind}_{counters[kind]}>"

        # Ordered most-specific first. Email before phone, because an email
        # local part can contain digit runs a phone pattern would match; NIC
        # and passport before the generic card candidate for the same reason.
        matchers: list[tuple[str, re.Pattern[str], object]] = [
            ("EMAIL", _EMAIL, None),
            ("NIC", _NIC_OLD, _nic_old_valid),
            ("NIC", _NIC_NEW, None),
            ("PASSPORT", _PASSPORT, None),
            ("CARD", _CARD_CANDIDATE, luhn_valid),
            ("PHONE", _PHONE, None),
        ]

        # Spans already claimed, so a later pattern cannot redact inside an
        # earlier placeholder.
        claimed: list[tuple[int, int]] = []

        for kind, pattern, validator in matchers:
            for match in pattern.finditer(text):
                start, end = match.span()
                if any(start < ce and end > cs for cs, ce in claimed):
                    continue
                value = match.group()
                if validator is not None and not validator(value):  # type: ignore[operator]
                    continue
                findings.append(
                    PiiFinding(
                        kind=kind,
                        placeholder=claim(kind),
                        original=value,
                        start=start,
                        end=end,
                    )
                )
                claimed.append((start, end))

        # Replace right-to-left so earlier offsets stay valid.
        for finding in sorted(findings, key=lambda f: f.start, reverse=True):
            text = text[: finding.start] + finding.placeholder + text[finding.end :]

    for finding in findings:
        trace.transformations.append(
            Transformation(
                kind=f"pii_redacted_{finding.kind.lower()}",
                # The original value is deliberately NOT recorded in the trace:
                # traces are logged and persisted, so storing it would defeat
                # the redaction.
                detail=f"replaced with {finding.placeholder}",
                after=finding.placeholder,
            )
        )

    if findings:
        trace.reason_codes.extend([ReasonCode.PII_DETECTED, ReasonCode.PII_REDACTED])

    trace.notes = {
        "finding_count": len(findings),
        "kinds": sorted({f.kind for f in findings}),
    }

    return RedactionResult(text=text, original=original, findings=findings, trace=trace)
