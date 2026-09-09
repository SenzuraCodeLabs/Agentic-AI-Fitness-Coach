"""L3 jargon expansion: correctness, and the guards on fuzzy correction."""

from __future__ import annotations

import pytest

from services.agent1_gatekeeper.pipeline.l3_lexicon import (
    _load_jargon,
    expand_jargon,
)


def expand(text: str):
    return expand_jargon(text, record_candidates=False)


def test_dictionary_meets_the_size_requirement():
    assert len(_load_jargon()) >= 200


@pytest.mark.parametrize(
    "abbreviation,expected",
    [
        ("ohp", "overhead press"),
        ("rdl", "romanian deadlift"),
        ("rpe", "rate of perceived exertion"),
        ("rir", "reps in reserve"),
        ("amrap", "as many reps as possible"),
        ("emom", "every minute on the minute"),
        ("doms", "delayed onset muscle soreness"),
        ("1rm", "one rep maximum"),
        ("delts", "deltoids"),
        ("lats", "latissimus dorsi"),
        ("quads", "quadriceps"),
        ("hammies", "hamstrings"),
        ("gvt", "german volume training"),
        ("macros", "macronutrients"),
    ],
)
def test_core_jargon_expands(abbreviation, expected):
    assert expected in expand(f"did some {abbreviation} today").text


def test_leftmost_longest_prevents_partial_expansion():
    """'bench press' must not be mangled by the shorter 'bench'."""
    assert expand("bench press").text == "barbell bench press"


def test_expansion_is_idempotent():
    """Re-expanding a canonical form must not change it further."""
    once = expand("lat pulldown and OHP").text
    assert expand(once).text == once


def test_word_boundaries_are_respected():
    """'bar' must not fire inside 'barbecue'."""
    assert "barbecue" in expand("had a barbecue after").text


def test_genuine_typos_are_corrected():
    result = expand("did some dealift and squts today")
    assert "conventional deadlift" in result.text
    assert "barbell back squat" in result.text


@pytest.mark.parametrize("word", ["week", "some", "might", "sore", "today", "more"])
def test_ordinary_english_words_are_never_rewritten(word):
    """Regression: WRatio scored these ~90 against long gym phrases and
    corrupted the user's text. A wrong correction is worse than none."""
    text = f"I trained {word} and felt fine"
    assert word in expand(text).text


def test_short_tokens_are_not_fuzzy_matched():
    """Below the length floor, coincidental matches dominate."""
    result = expand("rp is not pr")
    assert all(m.method != "fuzzy" or len(m.surface) >= 4 for m in result.matches)


def test_unknown_terms_are_left_alone_and_recorded():
    result = expand("did some zercher kroc rows and jefferson curls")
    assert result.oov_terms


def test_multiple_jargon_terms_in_one_sentence():
    result = expand("hit a PR on bench today, 3x5 at RPE 8")
    canonical = result.canonical_terms
    assert "personal record" in canonical
    assert "barbell bench press" in canonical
    assert "rate of perceived exertion" in canonical


def test_trace_records_counts_for_explainability():
    result = expand("did OHP and RDLs")
    notes = result.trace.notes
    assert notes["exact_matches"] >= 2
    assert notes["dictionary_size"] >= 200


def test_empty_input_is_safe():
    assert expand("").text == ""


def test_case_is_handled():
    assert "overhead press" in expand("did OHP").text
    assert "overhead press" in expand("did ohp").text
