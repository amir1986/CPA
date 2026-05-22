"""/knowledge — concept↔standard↔paragraph graph for the Sources screen."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.auth import RequestPrincipal, current_principal
from app.rag.knowledge_graph import build_graph


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class GraphNode(BaseModel):
    id: str
    label: str
    type: Literal["concept", "standard", "paragraph"]
    jurisdiction: str | None = None
    corpus_type: str | None = None
    language: str | None = None
    url: str | None = None
    excerpt: str | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    weight: int = 1
    kind: str = "references"


class GraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool
    chunk_count: int


@router.get("/graph", response_model=GraphOut)
async def graph(
    jurisdiction: list[str] | None = Query(default=None),
    corpus_type: list[str] | None = Query(default=None),
    max_nodes: int = Query(default=200, ge=10, le=1000),
    _: RequestPrincipal = Depends(current_principal),
) -> GraphOut:
    g = await build_graph(
        jurisdictions=jurisdiction,
        corpus_types=corpus_type,
        max_nodes=max_nodes,
    )
    return GraphOut(
        nodes=[GraphNode(**n.__dict__) for n in g.nodes],
        edges=[GraphEdge(**e.__dict__) for e in g.edges],
        truncated=g.truncated,
        chunk_count=g.chunk_count,
    )
