"""L3 - Gym jargon expansion.

Purpose: map the many ways lifters write a term onto one standardised form, so
extraction, retrieval and progress tracking all key off the same string. "OHP",
"military press" and "strict press" must become one exercise, or a user's
progression history silently splits into three.

ALGORITHM: AHO-CORASICK, AND WHY IT MATTERS
-------------------------------------------
The naive implementation loops over the dictionary calling ``str.replace``:

    for pattern, replacement in jargon.items():   # m patterns
        text = text.replace(pattern, replacement)  # O(n) scan each

That is O(n * m): every pattern rescans the whole input. With 619 patterns each
input is scanned 619 times. It also has a correctness bug, since an earlier
replacement can create or destroy a later pattern's match, so the result depends
on dictionary order.

Aho-Corasick builds a trie of all patterns once, augmented with failure links
that say where to continue when a match breaks. Matching is then a single pass:
O(n + z), where n is input length and z the number of matches, INDEPENDENT of
dictionary size. Construction is O(sum of pattern lengths), paid once at module
load, not per request.

Concretely at 619 patterns and a 200-character input: ~123,800 character
comparisons for the loop versus ~200 for the automaton, and the automaton's
result does not depend on dictionary ordering.

The layer also handles the leftmost-longest problem. "bench press" and "bench"
both match at the same position; the automaton reports both, and this code keeps
the longest, so "bench press" is not mangled into "barbell bench press press".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import ahocorasick
from rapidfuzz import fuzz, process

from services.agent1_gatekeeper.pipeline.base import LayerTrace, Timer, Transformation

LAYER_VERSION = "l3-1.0"

RESOURCES = Path(__file__).resolve().parent.parent / "resources"
CANDIDATES_FILE = RESOURCES / "oov_candidates.txt"

# rapidfuzz similarity below which a token is NOT corrected. Set high on
# purpose: a wrong correction silently rewrites what the user said, which is
# worse than leaving an unknown token alone for the extractor to handle.
FUZZY_THRESHOLD = 88

# Tokens shorter than this are not fuzzy-matched. Short strings hit the
# threshold by coincidence ("rp" vs "pr" scores highly but means something
# entirely different).
MIN_FUZZY_LEN = 4

_TOKEN_RE = re.compile(r"[a-z][a-z0-9'-]{2,}", re.IGNORECASE)

# Ordinary English words that must never be treated as a misspelled gym term.
# Every entry here was observed being wrongly "corrected" during development.
_NEVER_CORRECT = frozenset(
    """week weeks some sore more most much many might must make made take
    time times today tomorrow yesterday then than that this these those with
    without been being have has had here there where when what which while
    were was will would could should good great best better feel felt feels
    hard easy well very just only also about after before back next last
    first second third from into over under between during still even
    same other another each both all any few not but and the for you your
    day days morning night weekend month year going went gone doing
    done did does say said tell told want need like love hate think know
    long short high low big small new old right left top down out off
    session sessions plan plans start started stop stopped keep kept
    try tried trying help helped since ago""".split()
)

# Word characters for boundary checking. A match is only accepted when it is
# not embedded inside a larger word, otherwise "bar" would fire inside
# "barbecue" and "pr" inside "press".
_WORD_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


@dataclass(slots=True)
class JargonMatch:
    start: int
    end: int
    surface: str
    canonical: str
    method: str  # "exact" or "fuzzy"
    score: float = 100.0


@dataclass(slots=True)
class LexiconResult:
    text: str
    original: str
    matches: list[JargonMatch] = field(default_factory=list)
    oov_terms: list[str] = field(default_factory=list)
    trace: LayerTrace | None = None

    @property
    def canonical_terms(self) -> list[str]:
        """Deduplicated standardised terms found, in order of appearance."""
        seen: dict[str, None] = {}
        for m in self.matches:
            seen[m.canonical] = None
        return list(seen)


@lru_cache(maxsize=1)
def _load_jargon() -> dict[str, str]:
    path = RESOURCES / "jargon_map.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("map", {})


@lru_cache(maxsize=1)
def _automaton() -> ahocorasick.Automaton:
    """Build the Aho-Corasick automaton once per process.

    Cached because construction costs O(total pattern length). Rebuilding per
    request would make the layer slower than the naive loop it replaces, which
    is the classic way this optimisation gets accidentally reversed.
    """
    automaton = ahocorasick.Automaton()
    for pattern, canonical in _load_jargon().items():
        automaton.add_word(pattern, (pattern, canonical))
    if len(automaton):
        automaton.make_automaton()
    return automaton


@lru_cache(maxsize=1)
def _known_terms() -> tuple[str, ...]:
    """Vocabulary for fuzzy matching: both the variants and the canonical forms."""
    jargon = _load_jargon()
    return tuple(sorted(set(jargon.keys()) | set(jargon.values())))


def _has_word_boundary(text: str, start: int, end: int) -> bool:
    """True when [start:end) is not embedded inside a larger word."""
    before_ok = start == 0 or text[start - 1] not in _WORD_CHARS
    after_ok = end >= len(text) or text[end] not in _WORD_CHARS
    return before_ok and after_ok


def _find_exact(text: str) -> list[JargonMatch]:
    """One O(n) pass, then leftmost-longest resolution."""
    lowered = text.lower()
    automaton = _automaton()
    if not len(automaton):
        return []

    raw: list[JargonMatch] = []
    # pyahocorasick reports (end_index, value) for every pattern ending here.
    for end_idx, (pattern, canonical) in automaton.iter(lowered):
        start = end_idx - len(pattern) + 1
        end = end_idx + 1
        if not _has_word_boundary(lowered, start, end):
            continue
        raw.append(
            JargonMatch(
                start=start,
                end=end,
                surface=text[start:end],
                canonical=canonical,
                method="exact",
            )
        )

    # Leftmost-longest: sort by start, then by descending length, and greedily
    # take non-overlapping matches. This is what stops "bench press" being
    # broken up by the shorter "bench".
    raw.sort(key=lambda m: (m.start, -(m.end - m.start)))
    chosen: list[JargonMatch] = []
    cursor = -1
    for m in raw:
        if m.start >= cursor:
            chosen.append(m)
            cursor = m.end
    return chosen


def _find_oov(text: str, covered: list[JargonMatch]) -> list[str]:
    """Alphabetic tokens not covered by an exact match."""
    spans = [(m.start, m.end) for m in covered]
    out: list[str] = []
    for match in _TOKEN_RE.finditer(text):
        s, e = match.span()
        if any(s < ce and e > cs for cs, ce in spans):
            continue
        out.append(match.group().lower())
    return out


def _fuzzy_correct(oov: list[str]) -> dict[str, tuple[str, float]]:
    """Map likely typos to known terms above the similarity threshold.

    Three guards, all learned from observed misbehaviour rather than added
    speculatively. The first version of this used ``WRatio`` against the whole
    vocabulary and produced corruptions like "week" -> "deload",
    "sore" -> "delayed onset muscle soreness" and "might" -> "hip thrust".

    1. ``ratio``, not ``WRatio``. WRatio rewards partial substring overlap, so
       a short common word scores ~90 against a long multi-word term that
       merely contains a similar fragment. Plain Levenshtein ratio compares the
       strings as wholes, which is the actual question: is this a misspelling
       of that?

    2. A stoplist of ordinary English words. "week", "some", "might" and "sore"
       are not gym jargon and must never be rewritten, however they score.

    3. A length-ratio guard. A real typo is close in length to its target;
       a 4-character token is not a misspelling of a 28-character phrase.

    Anything not confidently corrected is left exactly as the user wrote it and
    logged as a dictionary candidate. Leaving an unknown token alone is always
    safer than silently changing the user's meaning.
    """
    corrections: dict[str, tuple[str, float]] = {}
    vocabulary = _known_terms()
    if not vocabulary:
        return corrections

    for token in set(oov):
        if len(token) < MIN_FUZZY_LEN or token in _NEVER_CORRECT:
            continue
        hit = process.extractOne(token, vocabulary, scorer=fuzz.ratio)
        if not hit or hit[1] < FUZZY_THRESHOLD:
            continue
        candidate = hit[0]
        # Length guard: a typo stays roughly the same length as its target.
        if not (0.6 <= len(token) / max(len(candidate), 1) <= 1.6):
            continue
        corrections[token] = (candidate, float(hit[1]))
    return corrections


def _record_candidates(terms: list[str]) -> None:
    """Append unknown terms to the candidates file so the dictionary can grow.

    Best-effort: a failure to write must never break a user request, so the
    error is swallowed. This is a data-collection convenience, not a control.
    """
    if not terms:
        return
    try:
        CANDIDATES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with CANDIDATES_FILE.open("a", encoding="utf-8") as fh:
            for t in terms:
                fh.write(f"{t}\n")
    except OSError:
        pass


def expand_jargon(text: str, *, record_candidates: bool = True) -> LexiconResult:
    """Expand gym jargon in ``text`` to standardised terms."""
    trace = LayerTrace(layer="L3_lexicon", version=LAYER_VERSION)
    original = text

    with Timer(trace):
        matches = _find_exact(text)
        oov = _find_oov(text, matches)
        corrections = _fuzzy_correct(oov)

        # Fold accepted fuzzy corrections in as matches so the rewrite below
        # handles exact and fuzzy uniformly.
        if corrections:
            jargon = _load_jargon()
            for match in _TOKEN_RE.finditer(text):
                token = match.group().lower()
                if token not in corrections:
                    continue
                corrected, score = corrections[token]
                s, e = match.span()
                if any(s < m.end and e > m.start for m in matches):
                    continue
                matches.append(
                    JargonMatch(
                        start=s,
                        end=e,
                        surface=match.group(),
                        canonical=jargon.get(corrected, corrected),
                        method="fuzzy",
                        score=score,
                    )
                )
            matches.sort(key=lambda m: m.start)

        # Rewrite right-to-left so earlier offsets stay valid.
        expanded = text
        for m in sorted(matches, key=lambda m: m.start, reverse=True):
            expanded = expanded[: m.start] + m.canonical + expanded[m.end :]

        unresolved = sorted(set(oov) - set(corrections))

    if record_candidates:
        _record_candidates(unresolved)

    for m in matches[:20]:
        trace.transformations.append(
            Transformation(
                kind=f"jargon_{m.method}",
                detail=f"score {m.score:.0f}" if m.method == "fuzzy" else "",
                before=m.surface,
                after=m.canonical,
            )
        )

    trace.notes = {
        "exact_matches": sum(1 for m in matches if m.method == "exact"),
        "fuzzy_matches": sum(1 for m in matches if m.method == "fuzzy"),
        "oov_count": len(unresolved),
        "dictionary_size": len(_load_jargon()),
    }

    return LexiconResult(
        text=expanded,
        original=original,
        matches=matches,
        oov_terms=unresolved,
        trace=trace,
    )
