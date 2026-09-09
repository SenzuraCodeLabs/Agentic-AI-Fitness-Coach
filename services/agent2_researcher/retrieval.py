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

    Chroma persists to disk, so seeding is idempotent: the count check means a
    restart does not re-embed the corpus.
    """
    import chromadb

    settings = get_settings()
    client = chromadb.PersistentClient(path=settings.chroma_path)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "l2"},
    )

    if collection.count() == 0:
        log.info("seeding_corpus", chunks=len(CORPUS))
        embeddings = _embedder().encode(
            [c["text"] for c in CORPUS],
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        collection.add(
            ids=[c["id"] for c in CORPUS],
            documents=[c["text"] for c in CORPUS],
            embeddings=[e.tolist() for e in embeddings],
            metadatas=[{"source": c["source"], "topic": c["topic"]} for c in CORPUS],
        )
        log.info("corpus_seeded", count=collection.count())

    return collection


def retrieve(query: str, top_k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
    """Return the most relevant evidence chunks for ``query``.

    Every chunk carries its source, so the coach can cite what it used.
    """
    if not query.strip():
        return []

    collection = _collection()
    query_vector = _embedder().encode([query], normalize_embeddings=True, show_progress_bar=False)

    results = collection.query(
        query_embeddings=[query_vector[0].tolist()],
        n_results=min(top_k, collection.count()),
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
                # Reported as similarity rather than distance because that is
                # the intuitive direction for a reader of the transparency
                # panel. Scaled across the accepted band so a chunk at the
                # threshold reads as 0 and an exact match as 1, rather than
                # compressing every real result into the bottom of the range.
                "score": round(max(0.0, 1.0 - dist / MAX_DISTANCE), 4),
            }
        )

    log.info("retrieval_complete", query_length=len(query), returned=len(chunks))
    return chunks


def warm_up() -> None:
    """Load the model and seed the collection at startup."""
    _collection()
    log.info("retrieval_warm", corpus_size=len(CORPUS))
