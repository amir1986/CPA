"""Embeddings facade.

Two backends:
- ``HashEmbedder`` (default) — deterministic 256-dim hash-mod embedding so
  the whole RAG pipeline runs end-to-end in CI without downloading models.
- ``MultilingualE5Embedder`` — real ``intfloat/multilingual-e5-large`` when
  ``CPA_EMBED_BACKEND=e5`` and sentence-transformers is installed.

The product wires E5 in dev/prod via Docker bake; tests use the hash backend.
"""

from __future__ import annotations

import hashlib
import math
import os
from typing import Protocol

HASH_DIM = 256


class Embedder(Protocol):
    def dim(self) -> int: ...

    def embed_text(self, text: str) -> list[float]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashEmbedder:
    """Deterministic feature-hashing embedding, L2-normalized."""

    def __init__(self, dim: int = HASH_DIM) -> None:
        self._dim = dim

    def dim(self) -> int:
        return self._dim

    def _embed(self, text: str) -> list[float]:
        if not text:
            return [0.0] * self._dim
        vec = [0.0] * self._dim
        # 3-gram token hashing is robust across EN/HE without language packs.
        for token in text.lower().split():
            for g in _ngrams(token, 3):
                h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
                idx = h % self._dim
                sign = 1.0 if (h >> 7) & 1 else -1.0
                vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0:
            return vec
        return [x / norm for x in vec]

    def embed_text(self, text: str) -> list[float]:
        return self._embed(text)

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def _ngrams(s: str, n: int) -> list[str]:
    if len(s) <= n:
        return [s]
    return [s[i : i + n] for i in range(len(s) - n + 1)]


class MultilingualE5Embedder:
    """Real E5 embeddings — loaded lazily."""

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer  # heavy import

        from app.config import get_settings

        s = get_settings()
        self._model = SentenceTransformer(s.embed_model, device=s.embed_device)
        # E5 large is 1024-dim.
        self._dim = self._model.get_sentence_embedding_dimension() or 1024

    def dim(self) -> int:
        return self._dim

    def embed_text(self, text: str) -> list[float]:
        return self._model.encode(f"passage: {text}", normalize_embeddings=True).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self._model.encode(f"query: {text}", normalize_embeddings=True).tolist()


_singleton: Embedder | None = None


def get_embedder() -> Embedder:
    global _singleton
    if _singleton is None:
        backend = os.environ.get("CPA_EMBED_BACKEND", "hash").lower()
        _singleton = MultilingualE5Embedder() if backend == "e5" else HashEmbedder()
    return _singleton


def reset_embedder() -> None:
    global _singleton
    _singleton = None
