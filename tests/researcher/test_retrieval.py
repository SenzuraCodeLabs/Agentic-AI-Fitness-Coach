"""Vector retrieval over the evidence corpus."""

from __future__ import annotations

import pytest

from services.agent2_researcher.corpus import CORPUS
from services.agent2_researcher.retrieval import retrieve


def test_corpus_entries_all_carry_a_source():
    """Grounding is the point: a chunk without attribution cannot be cited."""
    for chunk in CORPUS:
        assert chunk["source"]
        assert chunk["text"]
        assert chunk["id"]


def test_corpus_ids_are_unique():
    ids = [c["id"] for c in CORPUS]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    "query,expected_topic",
    [
        ("how many sets per week should I do", "training volume"),
        ("what rep range builds muscle", "rep ranges"),
        ("when should I deload", "deload"),
        ("how much protein do I need", "protein intake"),
        ("how do I squat correctly", "squat technique"),
    ],
)
def test_relevant_chunks_are_retrieved(query, expected_topic):
    chunks = retrieve(query, top_k=4)
    assert chunks
    assert expected_topic in {c["topic"] for c in chunks}


def test_every_returned_chunk_carries_its_source():
    for chunk in retrieve("progressive overload", top_k=3):
        assert chunk["source"]
        assert 0.0 <= chunk["score"] <= 1.0


def test_unrelated_query_returns_little_or_nothing():
    """A citation to something irrelevant is worse than no citation: it looks
    grounded while being unsupported."""
    chunks = retrieve("what is the capital of France", top_k=4)
    assert len(chunks) <= 2


def test_empty_query_returns_nothing():
    assert retrieve("") == []


def test_top_k_is_respected():
    assert len(retrieve("training volume and intensity", top_k=2)) <= 2
