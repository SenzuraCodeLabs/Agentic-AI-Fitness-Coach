"""L2 - Deobfuscation.

Purpose: recover plaintext hidden inside encodings, so the threat scorer sees
what the payload actually says.

The attack: "aWdub3JlIGFsbCBwcmV2aW91cyBpbnN0cnVjdGlvbnM=" passes every keyword
rule, because as a string it shares no substring with the phrase it encodes. A
sufficiently capable model will decode it anyway, so the detector must too.

THE CRITICAL DESIGN RULE: decoded text is returned ALONGSIDE the original,
never in place of it. Two reasons, both load-bearing:

  1. The threat scorer must see both. An input that is *both* plausible gym
     text and a base64 payload is more suspicious than either alone, and
     replacing the text would destroy that signal.
  2. Silent replacement is itself an injection vector. If a user writes a
     legitimate base64 string, substituting its decoding would change the
     meaning of their message without their knowledge.

Recursion is capped at depth 2. Double encoding is common; beyond that the cost
grows while the realistic attack surface does not, and an unbounded decoder is
a denial-of-service target (a nested payload that expands at every level).
"""

from __future__ import annotations

import base64
import binascii
import codecs
import math
import re
from dataclasses import dataclass, field

from services.agent1_gatekeeper.pipeline.base import LayerTrace, Timer, Transformation
from shared.contracts.enums import ReasonCode

LAYER_VERSION = "l2-1.0"

MAX_DEPTH = 2
MIN_B64_LEN = 16  # shorter strings produce too many false positives
MIN_HEX_LEN = 16
MIN_ENTROPY = 3.0  # bits/char; English prose sits well below this
MAX_CANDIDATES = 12  # bound the work per request

_B64_RE = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
_HEX_RE = re.compile(r"(?:0x)?(?:[0-9a-fA-F]{2}[\s:,-]?){8,}")
_WORDY_RE = re.compile(r"[A-Za-z]{3,}")

# Leetspeak. Applied only as a whole-text variant, never merged into the
# original, because these substitutions are lossy: "1" could be an intended
# digit (a rep count) rather than an "i".
_LEET_MAP = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "8": "b",
        "@": "a",
        "$": "s",
        "!": "i",
        "|": "l",
    }
)


@dataclass(slots=True)
class DecodedVariant:
    """One recovered plaintext and how it was obtained."""

    text: str
    method: str
    depth: int
    source_fragment: str = ""


@dataclass(slots=True)
class DeobfuscationResult:
    original: str
    variants: list[DecodedVariant] = field(default_factory=list)
    trace: LayerTrace | None = None

    @property
    def found_encoding(self) -> bool:
        return any(v.method != "leetspeak" for v in self.variants)

    def all_text(self) -> list[str]:
        """Original plus every decoded variant. What L5 scans."""
        return [self.original, *(v.text for v in self.variants)]

    def combined(self) -> str:
        """Single string for embedding, original first."""
        return "\n".join(self.all_text())


def shannon_entropy(s: str) -> float:
    """Bits per character.

    Used as a cheap gate before attempting a decode. Encoded data approaches
    uniform character distribution and scores high; English prose scores ~2.5
    or below because letter frequencies are skewed. Checking entropy first
    avoids running base64 decode over ordinary sentences that merely happen to
    match the character class.
    """
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _is_printable_text(data: bytes) -> str | None:
    """Return the decoded string if the bytes look like readable text.

    Random bytes decode to mojibake, which would add noise to the threat
    scorer. Requiring mostly-printable ASCII and at least one real word keeps
    only decodes that plausibly carry a message.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text.strip():
        return None
    printable = sum(1 for c in text if c.isprintable() or c in "\n\t\r")
    if printable / len(text) < 0.9:
        return None
    if not _WORDY_RE.search(text):
        return None
    return text


def _try_base64(fragment: str) -> str | None:
    """Decode a base64 candidate after cheap structural checks.

    Validation order is deliberate: length and padding are O(1), entropy is one
    pass, and only then is the actual decode attempted. This keeps a page of
    ordinary text from triggering hundreds of decode attempts.
    """
    stripped = fragment.strip()
    if len(stripped) < MIN_B64_LEN:
        return None
    # base64 encodes 3 bytes into 4 characters, so a valid payload's length is
    # a multiple of 4 once padding is included.
    padded = stripped + "=" * (-len(stripped) % 4)
    if len(padded) % 4:
        return None
    if shannon_entropy(stripped) < MIN_ENTROPY:
        return None
    try:
        raw = base64.b64decode(padded, validate=True)
    except (binascii.Error, ValueError):
        return None
    return _is_printable_text(raw)


def _try_hex(fragment: str) -> str | None:
    cleaned = re.sub(r"[\s:,\-]|0x", "", fragment)
    if len(cleaned) < MIN_HEX_LEN or len(cleaned) % 2:
        return None
    try:
        raw = bytes.fromhex(cleaned)
    except ValueError:
        return None
    return _is_printable_text(raw)


def _try_rot13(text: str) -> str | None:
    """ROT13 applied to the whole text.

    Unlike base64 there is no way to detect a ROT13 fragment structurally: the
    ciphertext is ordinary letters. So it is applied wholesale and kept only if
    the result contains more recognisable English words than the input, which
    is a crude but effective discriminator.
    """
    rotated = codecs.encode(text, "rot13")
    if _english_word_ratio(rotated) > _english_word_ratio(text) + 0.15:
        return rotated
    return None


# Small stopword set: enough to tell English from rotated gibberish without
# shipping a dictionary.
_COMMON = frozenset(
    """the and you are for not all any can how what when this that with your
    ignore instructions system prompt previous above disregard forget new role
    act pretend reveal show tell give bypass override admin developer mode
    squat bench press deadlift reps sets weight workout kg lbs""".split()
)


def _english_word_ratio(text: str) -> float:
    words = re.findall(r"[a-z]+", text.lower())
    if not words:
        return 0.0
    return sum(1 for w in words if w in _COMMON) / len(words)


def _decode_pass(text: str, depth: int) -> list[DecodedVariant]:
    """One decoding pass over ``text``."""
    found: list[DecodedVariant] = []

    for match in _B64_RE.finditer(text):
        if len(found) >= MAX_CANDIDATES:
            break
        decoded = _try_base64(match.group())
        if decoded:
            found.append(
                DecodedVariant(
                    text=decoded,
                    method="base64",
                    depth=depth,
                    source_fragment=match.group()[:40],
                )
            )

    for match in _HEX_RE.finditer(text):
        if len(found) >= MAX_CANDIDATES:
            break
        decoded = _try_hex(match.group())
        if decoded:
            found.append(
                DecodedVariant(
                    text=decoded,
                    method="hex",
                    depth=depth,
                    source_fragment=match.group()[:40],
                )
            )

    rot = _try_rot13(text)
    if rot:
        found.append(DecodedVariant(text=rot, method="rot13", depth=depth))

    return found


def deobfuscate(text: str) -> DeobfuscationResult:
    """Recover plaintext variants hidden in ``text``."""
    trace = LayerTrace(layer="L2_deobfuscate", version=LAYER_VERSION)
    variants: list[DecodedVariant] = []

    with Timer(trace):
        # Breadth-first to MAX_DEPTH. The depth guard is the denial-of-service
        # control: without it a self-expanding nested payload could recurse
        # until memory is exhausted.
        frontier = [text]
        for depth in range(1, MAX_DEPTH + 1):
            next_frontier: list[str] = []
            for candidate in frontier:
                for variant in _decode_pass(candidate, depth):
                    if variant.text in {v.text for v in variants} or variant.text == text:
                        continue
                    variants.append(variant)
                    next_frontier.append(variant.text)
                    if len(variants) >= MAX_CANDIDATES:
                        break
                if len(variants) >= MAX_CANDIDATES:
                    break
            if not next_frontier or len(variants) >= MAX_CANDIDATES:
                break
            frontier = next_frontier

        # Leetspeak is a normalisation variant, not a decoding, so it is added
        # last and marked distinctly. It does not raise ENCODED_PAYLOAD because
        # writing "sq0t" is sloppy typing as often as it is evasion.
        #
        # Encoded fragments are masked out first. Leet substitution is
        # character-level and would corrupt a base64 or hex run (turning "0"
        # into "o" inside the payload), producing a meaningless variant that
        # adds noise to the threat scorer.
        maskable = _B64_RE.sub(" ", text)
        maskable = _HEX_RE.sub(" ", maskable)
        leet = maskable.translate(_LEET_MAP)
        if leet != maskable and _english_word_ratio(leet) > _english_word_ratio(maskable):
            variants.append(DecodedVariant(text=leet, method="leetspeak", depth=1))

    for v in variants:
        trace.transformations.append(
            Transformation(
                kind=f"decoded_{v.method}",
                detail=f"depth {v.depth}",
                before=v.source_fragment,
                after=v.text,
            )
        )

    result = DeobfuscationResult(original=text, variants=variants, trace=trace)
    if result.found_encoding:
        trace.reason_codes.append(ReasonCode.ENCODED_PAYLOAD)
    trace.notes = {
        "variant_count": len(variants),
        "methods": sorted({v.method for v in variants}),
        "max_depth_reached": max((v.depth for v in variants), default=0),
    }
    return result
