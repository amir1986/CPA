"""End-to-end ingest pipeline: source → documents → chunks → vectors → store.

Pure orchestration. Fetching and parsing are stubbed via injectable callables
so tests pass synthetic documents through the same chunk → embed → upsert
path, and the production code drops in HTTP fetch + HTML parsing.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

from app.domain.models import Chunk
from app.embeddings import get_embedder
from app.ingest_standards.registry import Source
from app.rag.chunker import chunk_text
from app.rag.vector_store import CPA_KNOWLEDGE, StoredPoint, get_vector_store


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchedDocument:
    url: str
    text: str
    standard: str | None = None
    paragraph: str | None = None


Fetcher = Callable[[Source], Awaitable[list[FetchedDocument]]]


def _point_id(source_id: str, url: str, content_sha1: str) -> str:
    """Deterministic UUIDv5 for ``(source, url, sha1)`` so re-ingest is idempotent."""
    name = f"{source_id}|{url}|{content_sha1}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))


async def ingest_source(
    source: Source,
    *,
    fetcher: Fetcher,
    full_resync: bool = False,
) -> int:
    """Ingest a single source. Returns the number of chunks upserted."""
    store = get_vector_store()
    embedder = get_embedder()

    if full_resync:
        await store.delete_by_source(CPA_KNOWLEDGE, source.id)

    docs = await fetcher(source)
    points: list[StoredPoint] = []
    now = datetime.now(tz=timezone.utc)

    for doc in docs:
        for piece in chunk_text(doc.text):
            content_sha1 = hashlib.sha1(piece.text.encode("utf-8")).hexdigest()
            chunk = Chunk(
                source_id=source.id,
                standard=doc.standard,
                paragraph=doc.paragraph,
                jurisdiction=source.jurisdiction,
                corpus_type=source.corpus_type,
                language=source.language,
                url=doc.url,
                text=piece.text,
                content_sha1=content_sha1,
                fetched_at=now,
            )
            point_id = _point_id(source.id, doc.url, content_sha1)
            emb = embedder.embed_text(piece.text)
            points.append(StoredPoint(id=point_id, embedding=emb, chunk=chunk))

    await store.upsert(CPA_KNOWLEDGE, points)
    logger.info("ingest done: source=%s docs=%d chunks=%d", source.id, len(docs), len(points))
    return len(points)
