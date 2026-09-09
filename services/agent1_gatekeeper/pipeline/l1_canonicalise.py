"""L1 - Unicode canonicalisation.

Purpose: collapse the many visual spellings of a string into one form, so that
later layers match on text rather than on an attacker's chosen encoding of it.

The attack this defeats: every downstream detector is ultimately a string or
embedding comparison. "ignore previous instructions" written with a Cyrillic
'о', a zero-width space after "ig", or in mathematical bold looks identical to
a human and to an LLM, but is a different byte sequence to a regex. Without
canonicalisation the rule layer is trivially bypassed.

Order is deliberate and each step justifies its position:

  1. NFKC              expands compatibility forms (fullwidth, ligatures,
                       superscripts) into their ASCII equivalents. Done first
                       because it removes ~85% of homoglyph candidates by
                       itself, so the map only handles what NFKC preserves.
  2. zero-width strip  these are invisible and carry no linguistic meaning
                       here, so removing them cannot change intent.
  3. bidi strip        override characters can reverse displayed order, so
                       what a reviewer reads is not what a parser sees.
  4. homoglyph fold    Cyrillic/Greek lookalikes. NFKC deliberately keeps
                       these, because they are legitimately different letters
                       in their own scripts; folding is a domain decision that
                       this app is English-only.
  5. repetition        "ignooooore" defeats exact matching but not meaning.
  6. whitespace        normalise runs to single spaces.

The result carries a list of every transformation applied. That list is
evidence: it is what lets the security report say an input was obfuscated and
exactly how.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from services.agent1_gatekeeper.pipeline.base import LayerTrace, Timer, Transformation
from shared.contracts.enums import ReasonCode

LAYER_VERSION = "l1-1.0"

RESOURCES = Path(__file__).resolve().parent.parent / "resources"

# Zero-width and formatting characters. These are invisible, so they exist in
# user input almost exclusively to split a keyword.
ZERO_WIDTH = {
    "​",  # zero width space
    "‌",  # zero width non-joiner
    "‍",  # zero width joiner
    "‎",  # left-to-right mark
    "‏",  # right-to-left mark
    "﻿",  # zero width no-break space / BOM
    "⁠",  # word joiner
    "᠎",  # mongolian vowel separator
    "­",  # soft hyphen
}

# Bidirectional override characters. A "trojan source" style attack uses these
# so displayed order differs from logical order.
BIDI_OVERRIDES = {
    "‪",  # left-to-right embedding
    "‫",  # right-to-left embedding
    "‬",  # pop directional formatting
    "‭",  # left-to-right override
    "‮",  # right-to-left override
    "⁦",  # left-to-right isolate
    "⁧",  # right-to-left isolate
    "⁨",  # first strong isolate
    "⁩",  # pop directional isolate
}

# Unusual spaces that are not matched by \s in every context.
EXOTIC_SPACE = {
    " ",  # no-break space
    " ",  # ogham space mark
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",  # en/em quad family
    " ",  # narrow no-break space
    " ",  # medium mathematical space
    "　",  # ideographic space
}

_REPEAT_RE = re.compile(r"(.)\1{2,}", re.DOTALL)
_WS_RE = re.compile(r"[ \t]{2,}")
_NEWLINE_RE = re.compile(r"\n{3,}")

# Cap on input length. Applied before the expensive passes so a huge payload
# cannot burn CPU; the gateway also enforces a limit, this is defence in depth.
MAX_INPUT_CHARS = 8000


@dataclass(slots=True)
class CanonicalisationResult:
    text: str
    original: str
    transformations: list[Transformation] = field(default_factory=list)
    trace: LayerTrace | None = None

    @property
    def was_modified(self) -> bool:
        return self.text != self.original

    @property
    def suspicious(self) -> bool:
        """True when a transformation suggests deliberate obfuscation.

        Whitespace collapsing and NFKC are routine and appear in ordinary text,
        so they do not count. Invisible characters and homoglyphs in an
        English-only fitness app effectively never occur by accident.
        """
        return any(
            t.kind in {"zero_width_removed", "bidi_removed", "homoglyph_folded"}
            for t in self.transformations
        )


@lru_cache(maxsize=1)
def _load_confusables() -> dict[str, str]:
    """Load and cache the homoglyph map.

    Cached at module level: this is called per request and re-reading a JSON
    file each time would dominate the layer's latency budget.
    """
    path = RESOURCES / "confusables.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("map", {})


@lru_cache(maxsize=1)
def _translation_table() -> dict[int, str]:
    """Pre-build a str.translate table.

    ``str.translate`` runs the whole substitution in one C-level pass, versus
    one Python-level scan per entry for repeated ``str.replace``. With 137
    entries that is the difference between one pass and 137.
    """
    return {ord(k): v for k, v in _load_confusables().items()}


def canonicalise(text: str) -> CanonicalisationResult:
    """Normalise ``text`` and report every transformation applied."""
    trace = LayerTrace(layer="L1_canonicalise", version=LAYER_VERSION)
    transformations: list[Transformation] = []
    original = text

    with Timer(trace):
        if len(text) > MAX_INPUT_CHARS:
            transformations.append(
                Transformation(
                    kind="truncated",
                    detail=f"input clipped from {len(text)} to {MAX_INPUT_CHARS} chars",
                )
            )
            text = text[:MAX_INPUT_CHARS]

        # 1. NFKC compatibility normalisation.
        nfkc = unicodedata.normalize("NFKC", text)
        if nfkc != text:
            transformations.append(Transformation(kind="nfkc_normalised", before=text, after=nfkc))
            text = nfkc

        # 2. Zero-width characters.
        zw_count = sum(text.count(c) for c in ZERO_WIDTH)
        if zw_count:
            for c in ZERO_WIDTH:
                text = text.replace(c, "")
            transformations.append(
                Transformation(
                    kind="zero_width_removed",
                    detail="invisible characters that split keywords",
                    count=zw_count,
                )
            )

        # 3. Bidi overrides.
        bidi_count = sum(text.count(c) for c in BIDI_OVERRIDES)
        if bidi_count:
            for c in BIDI_OVERRIDES:
                text = text.replace(c, "")
            transformations.append(
                Transformation(
                    kind="bidi_removed",
                    detail="direction overrides can hide text from a reviewer",
                    count=bidi_count,
                )
            )

        # 4. Exotic spaces to plain spaces, before whitespace collapsing.
        exotic = sum(text.count(c) for c in EXOTIC_SPACE)
        if exotic:
            for c in EXOTIC_SPACE:
                text = text.replace(c, " ")
            transformations.append(Transformation(kind="exotic_space_normalised", count=exotic))

        # 5. Homoglyph folding.
        table = _translation_table()
        folded = text.translate(table)
        if folded != text:
            changed = sum(1 for a, b in zip(text, folded, strict=False) if a != b)
            transformations.append(
                Transformation(
                    kind="homoglyph_folded",
                    detail="non-Latin lookalike characters mapped to Latin",
                    before=text,
                    after=folded,
                    count=changed,
                )
            )
            text = folded

        # 6. Excessive character repetition, capped at two.
        #    Two is kept because English has legitimate doubles ("bench press",
        #    "off"); three or more of the same letter is not ordinary text.
        derepeated = _REPEAT_RE.sub(lambda m: m.group(1) * 2, text)
        if derepeated != text:
            transformations.append(
                Transformation(
                    kind="repetition_collapsed",
                    detail="runs of 3+ identical characters reduced to 2",
                    before=text,
                    after=derepeated,
                )
            )
            text = derepeated

        # 7. Whitespace.
        collapsed = _WS_RE.sub(" ", text)
        collapsed = _NEWLINE_RE.sub("\n\n", collapsed)
        collapsed = collapsed.strip()
        if collapsed != text:
            transformations.append(Transformation(kind="whitespace_collapsed"))
            text = collapsed

    trace.transformations = transformations
    result = CanonicalisationResult(
        text=text, original=original, transformations=transformations, trace=trace
    )
    if result.suspicious:
        trace.reason_codes.append(ReasonCode.OBFUSCATED_TEXT)
    trace.notes = {
        "original_length": len(original),
        "final_length": len(text),
        "modified": result.was_modified,
        "suspicious": result.suspicious,
    }
    return result
