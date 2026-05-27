"""Qdrant-backed vector store.

Kept separate so the in-memory store works without importing qdrant_client.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.config import get_settings
from app.domain.models import Chunk, RetrievedChunk
from app.rag.vector_store import StoredPoint, VectorStore


class QdrantVectorStore(VectorStore):
    def __init__(self) -> None:
        from qdrant_client import AsyncQdrantClient

        settings = get_settings()
        api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
        self._client = AsyncQdrantClient(url=settings.qdrant_url, api_key=api_key)
        self._initialized: set[str] = set()

    async def _ensure_collection(self, collection: str, dim: int) -> None:
        if collection in self._initialized:
            return
        from qdrant_client.http import models as qm

        try:
            existing = await self._client.get_collection(collection)
            if existing is not None:
                self._initialized.add(collection)
                return
        except Exception:
            pass

        await self._client.create_collection(
            collection_name=collection,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
        )
        # Common payload indexes (best-effort — duplicate-index errors are fine).
        import contextlib
        for field, typ in (
            ("source_id", "keyword"),
            ("jurisdiction", "keyword"),
            ("corpus_type", "keyword"),
            ("language", "keyword"),
            ("standard", "keyword"),
        ):
            with contextlib.suppress(Exception):
                await self._client.create_payload_index(collection, field_name=field, field_schema=typ)
        self._initialized.add(collection)

    async def upsert(self, collection: str, points: list[StoredPoint]) -> None:
        if not points:
            return
        await self._ensure_collection(collection, dim=len(points[0].embedding))
        from qdrant_client.http import models as qm

        qpoints = [
            qm.PointStruct(
                id=p.id,
                vector=p.embedding,
                payload={
                    **{
                        k: v
                        for k, v in asdict(p.chunk).items()
                        if k != "text"   # text stored separately to keep payload small
                    },
                    "text": p.chunk.text,
                },
            )
            for p in points
        ]
        await self._client.upsert(collection_name=collection, points=qpoints)

    async def search(
        self,
        collection: str,
        *,
        query_embedding: list[float],
        query_text: str,
        top_k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        from qdrant_client.http import models as qm

        must = []
        for k, v in (filters or {}).items():
            if v is None:
                continue
            if isinstance(v, (list, tuple, set)):
                must.append(qm.FieldCondition(key=k, match=qm.MatchAny(any=list(v))))
            else:
                must.append(qm.FieldCondition(key=k, match=qm.MatchValue(value=v)))

        results = await self._client.search(
            collection_name=collection,
            query_vector=query_embedding,
            limit=top_k,
            query_filter=qm.Filter(must=must) if must else None,
        )
        out: list[RetrievedChunk] = []
        for r in results:
            p = r.payload or {}
            chunk = Chunk(
                source_id=p.get("source_id", ""),
                standard=p.get("standard"),
                paragraph=p.get("paragraph"),
                jurisdiction=p.get("jurisdiction", "US"),
                corpus_type=p.get("corpus_type", "accounting"),
                language=p.get("language", "en"),
                url=p.get("url", ""),
                text=p.get("text", ""),
                content_sha1=p.get("content_sha1", ""),
            )
            out.append(RetrievedChunk(chunk=chunk, score=float(r.score)))
        return out

    async def delete_by_source(self, collection: str, source_id: str) -> None:
        from qdrant_client.http import models as qm

        await self._client.delete(
            collection_name=collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[qm.FieldCondition(key="source_id", match=qm.MatchValue(value=source_id))]
                )
            ),
        )
