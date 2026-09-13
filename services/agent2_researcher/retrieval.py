"""Vector retrieval over the evidence corpus.

Uses ChromaDB with the same all-MiniLM-L6-v2 embeddings as L5. Sharing one
model means one download, one load, and one set of vector semantics across the
system.

A relevance floor is applied. Returning the nearest chunks regardless of
distance would hand the coach irrelevant evidence for an off-topic question,
and a citation to something irrelevant is worse than no citation: it looks
grounded while being unsupported.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from typing import Any

from services.agent2_researcher.corpus import CORPUS
from shared.config import get_settings
from shared.logging import get_logger

log = get_logger("agent2.retrieval")

COLLECTION_NAME = "fitcoach_evidence"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Chroma returns squared L2 distance for normalised vectors. Distance rises as
# relevance falls, so this is an upper bound: anything further away is dropped.
#
# 1.7 is measured, not guessed. An earlier value of 1.2 was set by intuition
# and silently discarded correct results: "when should I deload" matches its
# own chunk at 1.504 and was being dropped.
#
#   on-topic query, correct chunk        0.77 - 1.60
#   off-domain query, nearest chunk      1.86 - 1.96
#
# The gap between those bands is where the threshold belongs. This is the kind
# of parameter that has to be set from data, because a value that looks
# reasonable can be quietly discarding good answers.
MAX_DISTANCE = 1.7

DEFAULT_TOP_K = 4


@lru_cache(maxsize=1)
def _embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def _collection():
    """Open the persistent collection, seeding it on first use.

    A content fingerprint refreshes changed passages while an unchanged corpus
    avoids re-embedding across restarts.
    """
    import chromadb

    settings = get_settings()
    client = chromadb.PersistentClient(path=settings.chroma_path)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "l2"},
    )

    fingerprint = hashlib.sha256(json.dumps(CORPUS, sort_keys=True).encode()).hexdigest()
    if (collection.metadata or {}).get("corpus_hash") != fingerprint:
        log.info("seeding_corpus", chunks=len(CORPUS))
        embeddings = _embedder().encode(
            [c["text"] for c in CORPUS],
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        collection.upsert(
            ids=[c["id"] for c in CORPUS],
            documents=[c["text"] for c in CORPUS],
            embeddings=[e.tolist() for e in embeddings],
            metadatas=[
                {"source": c["source"], "topic": c["topic"], "url": c.get("url", "")}
                for c in CORPUS
            ],
        )
        # Remove only retired curated IDs, never unrelated imported documents.
        old_ids = json.loads((collection.metadata or {}).get("curated_ids", "[]"))
        retired = sorted(set(old_ids) - {c["id"] for c in CORPUS})
        if retired:
            collection.delete(ids=retired)
        collection.modify(
            metadata={
                "corpus_hash": fingerprint,
                "curated_ids": json.dumps([c["id"] for c in CORPUS]),
            }
        )
        log.info("corpus_seeded", count=collection.count())

    return collection


def retrieve(query: str, top_k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
    """Return the most relevant evidence chunks for ``query``.

    Every chunk carries its source, so the coach can cite what it used.
    """
    if not query.strip() or top_k <= 0:
        return []

    collection = _collection()
    query_vector = _embedder().encode([query], normalize_embeddings=True, show_progress_bar=False)

    results = collection.query(
        query_embeddings=[query_vector[0].tolist()],
        n_results=min(max(top_k * 4, 12), collection.count()),
    )

    chunks: list[dict[str, Any]] = []
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    ids = results.get("ids", [[]])[0]

    for doc, meta, dist, chunk_id in zip(documents, metadatas, distances, ids, strict=False):
        if dist > MAX_DISTANCE:
            continue
        chunks.append(
            {
                "id": chunk_id,
                "text": doc,
                "source": meta.get("source", "unknown"),
                "topic": meta.get("topic", ""),
                "url": meta.get("url", ""),
                # Reported as similarity rather than distance because that is
                # the intuitive direction for a reader of the transparency
                # panel. Scaled across the accepted band so a chunk at the
                # threshold reads as 0 and an exact match as 1, rather than
                # compressing every real result into the bottom of the range.
                "score": round(max(0.0, 1.0 - dist / MAX_DISTANCE), 4),
            }
        )

    chunks = rerank(query, chunks, top_k)
    log.info("retrieval_complete", query_length=len(query), returned=len(chunks))
    return chunks


_STOP = set(
    (
        "how what when should i my the a an to for of is do does can many much per in and at has"
    ).split()
)


def _terms(text: str) -> set[str]:
    words = set(re.findall(r"[a-z]+", text.lower())) - _STOP
    aliases = {
        "stalled": "stalling",
        "stuck": "stalling",
        "plateau": "stalling",
        "reps": "rep",
        "sets": "set",
        "weekly": "week",
        "correctly": "technique",
        "sleep": "recovery",
        "rpe": "autoregulation",
    }
    return {aliases.get(w, w) for w in words}


def rerank(query: str, chunks: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    """Blend topic/term relevance with dense similarity, then diversify sources.

    A source appears once and near-identical passages cannot fill the answer.
    Scores are ranking heuristics, not calibrated probabilities.
    """
    terms = _terms(query)
    ranked = []
    for chunk in chunks:
        topic_terms = _terms(chunk.get("topic", ""))
        overlap = len(terms & _terms(chunk["text"])) / max(len(terms), 1)
        topic = len(terms & topic_terms) / max(len(topic_terms), 1)
        score = 0.55 * chunk.get("score", 0) + 0.25 * overlap + 0.20 * topic
        if score >= 0.12:
            ranked.append({**chunk, "score": round(score, 4)})
    # Never pad strong topic results with distant neighbours just to reach k.
    relative_floor = max((c["score"] for c in ranked), default=0) * 0.55
    ranked = [c for c in ranked if c["score"] >= relative_floor]
    selected: list[dict[str, Any]] = []
    sources: set[str] = set()
    for chunk in sorted(ranked, key=lambda c: c["score"], reverse=True):
        source = (chunk.get("url") or chunk["source"]).strip().casefold()
        words = _terms(chunk["text"])
        duplicate = any(
            len(words & _terms(c["text"])) / max(len(words | _terms(c["text"])), 1) > 0.8
            for c in selected
        )
        if source in sources or duplicate:
            continue
        selected.append(chunk)
        sources.add(source)
        if len(selected) >= top_k:
            break
    return selected


def warm_up() -> None:
    """Load the model and seed the collection at startup."""
    _collection()
    log.info("retrieval_warm", corpus_size=len(CORPUS))
