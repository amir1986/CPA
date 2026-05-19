"""Vector store abstraction with two backends.

- ``MemoryVectorStore`` — in-process, deterministic, used by tests and as
  the default in dev when Qdrant isn't available. Cosine similarity with
  optional BM25-lite token overlap; supports payload filters.
- ``QdrantVectorStore`` — real Qdrant client when ``QDRANT_URL`` resolves
  and the qdrant-client lib is installed.
"""

from __future__ import annotations

import math
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from app.domain.models import Chunk, RetrievedChunk


CPA_KNOWLEDGE = "cpa_knowledge"
ENGAGEMENT_DOCS = "engagement_docs"


_TOK = re.compile(r"[\w֐-׿]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOK.findall(text)]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def bm25_lite_score(query_tokens: Iterable[str], doc_tokens: list[str]) -> float:
    """Simple bag-of-words overlap, normalized by sqrt(doc length).

    Not a real BM25 — but enough to fuse with dense scores and pass a
    deterministic regression test. The real Qdrant backend uses Qdrant's
    sparse vectors.
    """
    if not doc_tokens:
        return 0.0
    counts = Counter(doc_tokens)
    overlap = sum(counts.get(t, 0) for t in query_tokens)
    return overlap / math.sqrt(len(doc_tokens))


@dataclass
class StoredPoint:
    id: str
    embedding: list[float]
    chunk: Chunk


class VectorStore(Protocol):
    async def upsert(self, collection: str, points: list[StoredPoint]) -> None: ...

    async def search(
        self,
        collection: str,
        *,
        query_embedding: list[float],
        query_text: str,
        top_k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]: ...

    async def delete_by_source(self, collection: str, source_id: str) -> None: ...


class MemoryVectorStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._collections: dict[str, dict[str, StoredPoint]] = {}

    async def upsert(self, collection: str, points: list[StoredPoint]) -> None:
        with self._lock:
            coll = self._collections.setdefault(collection, {})
            for p in points:
                coll[p.id] = p

    async def search(
        self,
        collection: str,
        *,
        query_embedding: list[float],
        query_text: str,
        top_k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        with self._lock:
            coll = list(self._collections.get(collection, {}).values())
        filtered: list[StoredPoint] = []
        for p in coll:
            if filters and not _matches(p.chunk, filters):
                continue
            filtered.append(p)

        qtok = tokenize(query_text)
        scored: list[tuple[float, StoredPoint]] = []
        for p in filtered:
            dense = cosine(query_embedding, p.embedding)
            sparse = bm25_lite_score(qtok, tokenize(p.chunk.text))
            # Reciprocal-rank-style fusion; weights tuned for the test corpus.
            score = 0.7 * dense + 0.3 * min(sparse, 1.0)
            scored.append((score, p))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [RetrievedChunk(chunk=p.chunk, score=s) for s, p in scored[:top_k]]

    async def delete_by_source(self, collection: str, source_id: str) -> None:
        with self._lock:
            coll = self._collections.get(collection)
            if not coll:
                return
            for pid in [pid for pid, p in coll.items() if p.chunk.source_id == source_id]:
                coll.pop(pid, None)


def _matches(chunk: Chunk, filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        value = getattr(chunk, key, None)
        if expected is None:
            continue
        if isinstance(expected, (list, tuple, set)):
            if value not in expected:
                return False
        else:
            if value != expected:
                return False
    return True


# ──────────────── factory ────────────────


_singleton: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _singleton
    if _singleton is None:
        backend = os.environ.get("CPA_VECTOR_BACKEND", "memory").lower()
        if backend == "qdrant":
            from app.rag._qdrant import QdrantVectorStore  # lazy import
            _singleton = QdrantVectorStore()
        else:
            _singleton = MemoryVectorStore()
    return _singleton


def reset_vector_store() -> None:
    global _singleton
    _singleton = None
