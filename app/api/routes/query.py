"""/query — cited Q&A. Non-streaming and SSE variants."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import RequestPrincipal, current_principal
from app.api.schemas.query import (
    CitationOut,
    QueryIn,
    QueryOut,
    RetrievedOut,
)
from app.db.models.observability import QueryLog
from app.db.session import get_session
from app.domain.models import Citation
from app.rag.query_engine import answer_question

logger = logging.getLogger(__name__)

router = APIRouter(tags=["query"])


def _citation_out(c: Citation) -> CitationOut:
    return CitationOut(standard=c.standard, paragraph=c.paragraph, url=c.url, quote=c.quote)


@router.post("/query", response_model=QueryOut)
async def query(
    payload: QueryIn,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> QueryOut:
    result = await answer_question(
        payload.question,
        jurisdictions=payload.jurisdictions,
        corpus_types=payload.corpus_types,
        top_k=payload.top_k,
        min_score=payload.min_score,
    )

    session.add(
        QueryLog(
            user_id=principal.user_id if principal.user_id.int != 0 else None,
            question=payload.question,
            language=result.language,
            citations=[c.__dict__ for c in result.citations],
            refused=result.refused,
            created_at=datetime.now(tz=UTC),
        )
    )

    return QueryOut(
        answer=result.answer,
        citations=[_citation_out(c) for c in result.citations],
        refused=result.refused,
        language=result.language,
        retrieved=[
            RetrievedOut(
                standard=rc.chunk.standard,
                paragraph=rc.chunk.paragraph,
                url=rc.chunk.url,
                jurisdiction=rc.chunk.jurisdiction,
                corpus_type=rc.chunk.corpus_type,
                language=rc.chunk.language,
                score=rc.score,
            )
            for rc in result.retrieved
        ],
    )


@router.post("/query/stream")
async def query_stream(
    payload: QueryIn,
    principal: RequestPrincipal = Depends(current_principal),
) -> StreamingResponse:
    """SSE: emits `event: token` deltas as the LLM streams, then `event: done`.

    For Phase 2 we run the full ``answer_question`` first (so citations are
    validated) and then stream the final answer character-by-character. When
    the agent layer lands (Phase 9) the LLM will stream directly into this
    pipe with intermediate ``event: citation`` and ``event: tool_*`` frames.
    """
    result = await answer_question(
        payload.question,
        jurisdictions=payload.jurisdictions,
        corpus_types=payload.corpus_types,
        top_k=payload.top_k,
        min_score=payload.min_score,
    )

    async def gen() -> AsyncIterator[bytes]:
        # 2 KB preamble so Cloudflare / Render's edge flushes immediately
        # instead of buffering a short answer until enough bytes accumulate
        # (CLAUDE.md §3 SSE responses, commit 6b7a5b7).
        yield (b": " + b"x" * 2048 + b"\n\n")
        # Stream the answer body.
        chunk = result.answer
        # Yield in ~24-char pieces so a UI sees progressive deltas.
        for i in range(0, len(chunk), 24):
            piece = chunk[i : i + 24]
            yield f"event: token\ndata: {json.dumps({'delta': piece})}\n\n".encode()
            await asyncio.sleep(0)
        # One citation event per validated citation.
        for c in result.citations:
            data = {
                "standard": c.standard,
                "paragraph": c.paragraph,
                "url": c.url,
                "quote": c.quote,
            }
            yield f"event: citation\ndata: {json.dumps(data)}\n\n".encode()
        # Done.
        done = {"refused": result.refused, "language": result.language}
        yield f"event: done\ndata: {json.dumps(done)}\n\n".encode()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Content-Encoding": "identity",
            "X-Accel-Buffering": "no",   # nginx hint for SSE
        },
    )
