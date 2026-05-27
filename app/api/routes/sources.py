"""/sources — list configured standards sources."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.auth import RequestPrincipal, current_principal
from app.api.schemas.query import SourceOut
from app.ingest_standards.registry import load_sources

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=list[SourceOut])
async def list_sources(
    _: RequestPrincipal = Depends(current_principal),
) -> list[SourceOut]:
    return [
        SourceOut(
            id=s.id,
            name=s.name,
            url=s.url,
            corpus_type=s.corpus_type,
            jurisdiction=s.jurisdiction,
            language=s.language,
            licence=s.licence,
        )
        for s in load_sources()
    ]
