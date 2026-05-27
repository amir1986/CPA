"""Build a small concept↔standard↔paragraph graph for the Sources screen.

Strategy:
1. List a representative slice of the indexed corpus from the vector
   store (current MemoryVectorStore exposes ``_collections`` for this;
   the Qdrant backend uses ``scroll`` with a payload filter).
2. For each chunk, infer a "concept" from a small keyword catalog (the
   high-level topics that show up in the Compare screen — Revenue, Leases,
   Inventory, …).
3. Emit nodes for {concept, standard, paragraph} and edges
   ``concept --references--> standard`` and ``standard --has--> paragraph``.
4. Cap to ``max_nodes`` so the client render stays interactive.

Results are cached for ``ttl_seconds`` so a busy Sources page doesn't
hammer Qdrant.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from app.domain.models import Chunk
from app.rag.vector_store import CPA_KNOWLEDGE, MemoryVectorStore, VectorStore, get_vector_store

# Concept → matching regex (case-insensitive). Lifted from the Compare screen's
# topic picker so the two stay in sync.
CONCEPTS: list[tuple[str, re.Pattern[str]]] = [
    ("Revenue recognition", re.compile(r"revenue recognition|ASC 606|IFRS 15", re.IGNORECASE)),
    ("Leases", re.compile(r"\bleases?\b|ASC 842|IFRS 16", re.IGNORECASE)),
    ("Inventory", re.compile(r"\binventor(y|ies)\b|ASC 330|IAS 2", re.IGNORECASE)),
    ("Intangible assets", re.compile(r"intangible|goodwill|ASC 350|IAS 38", re.IGNORECASE)),
    ("Impairment", re.compile(r"impairment|IAS 36|ASC 360", re.IGNORECASE)),
    ("Financial instruments", re.compile(r"financial instruments|ASC 825|IFRS 9", re.IGNORECASE)),
    ("Income taxes", re.compile(r"income tax|ASC 740|IAS 12", re.IGNORECASE)),
    ("Audit risk", re.compile(r"audit risk|risk assessment|AU-?C 315|ISA 315", re.IGNORECASE)),
    ("Materiality", re.compile(r"materiality|AU-?C 320|ISA 320", re.IGNORECASE)),
    ("Going concern", re.compile(r"going concern|AU-?C 570|ISA 570", re.IGNORECASE)),
]


@dataclass
class Node:
    id: str
    label: str
    type: str           # concept | standard | paragraph
    jurisdiction: str | None = None
    corpus_type: str | None = None
    language: str | None = None
    url: str | None = None
    excerpt: str | None = None


@dataclass
class Edge:
    source: str
    target: str
    weight: int = 1
    kind: str = "references"


@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    truncated: bool = False
    chunk_count: int = 0


def _classify(text: str) -> list[str]:
    return [name for name, pat in CONCEPTS if pat.search(text)]


def _node(graph: Graph, seen: dict[str, Node], node: Node) -> None:
    if node.id not in seen:
        seen[node.id] = node
        graph.nodes.append(node)


def _edge(graph: Graph, seen: dict[tuple[str, str], Edge], source: str, target: str, kind: str) -> None:
    key = (source, target)
    if (e := seen.get(key)) is not None:
        e.weight += 1
        return
    e = Edge(source=source, target=target, kind=kind)
    seen[key] = e
    graph.edges.append(e)


async def _gather_chunks(
    store: VectorStore,
    *,
    jurisdictions: list[str] | None,
    corpus_types: list[str] | None,
    limit: int,
) -> list[Chunk]:
    # MemoryVectorStore (and Qdrant when present) → scan a slice of payloads.
    if isinstance(store, MemoryVectorStore):
        coll = store._collections.get(CPA_KNOWLEDGE, {})  # type: ignore[attr-defined]
        items = [p.chunk for p in coll.values()]
    else:
        # Qdrant scroll path — best-effort. The fallback returns the curated
        # nodes only when no real corpus is reachable.
        try:
            from qdrant_client.http import models as qm

            client = store._client  # type: ignore[attr-defined]
            must = []
            if jurisdictions:
                must.append(qm.FieldCondition(key="jurisdiction", match=qm.MatchAny(any=jurisdictions)))
            if corpus_types:
                must.append(qm.FieldCondition(key="corpus_type", match=qm.MatchAny(any=corpus_types)))
            res, _ = await client.scroll(
                collection_name=CPA_KNOWLEDGE,
                limit=limit,
                scroll_filter=qm.Filter(must=must) if must else None,
                with_payload=True,
                with_vectors=False,
            )
            items = []
            for point in res:
                p = point.payload or {}
                items.append(
                    Chunk(
                        source_id=p.get("source_id", ""),
                        standard=p.get("standard"),
                        paragraph=p.get("paragraph"),
                        jurisdiction=p.get("jurisdiction", ""),
                        corpus_type=p.get("corpus_type", ""),
                        language=p.get("language", ""),
                        url=p.get("url", ""),
                        text=p.get("text", ""),
                        content_sha1=p.get("content_sha1", ""),
                    )
                )
        except Exception:
            items = []

    if jurisdictions:
        items = [c for c in items if c.jurisdiction in jurisdictions]
    if corpus_types:
        items = [c for c in items if c.corpus_type in corpus_types]
    return items[:limit]


def _curated_graph() -> Graph:
    """Fallback graph used when the corpus is empty.

    Hand-curated GAAP ↔ IFRS pairings give the UI something useful to
    render before any ingest job has run.
    """
    g = Graph()
    seen_n: dict[str, Node] = {}
    seen_e: dict[tuple[str, str], Edge] = {}
    pairs = [
        ("Revenue recognition", "ASC 606", "US", "accounting"),
        ("Revenue recognition", "IFRS 15", "IFRS", "accounting"),
        ("Leases", "ASC 842", "US", "accounting"),
        ("Leases", "IFRS 16", "IFRS", "accounting"),
        ("Inventory", "ASC 330", "US", "accounting"),
        ("Inventory", "IAS 2", "IFRS", "accounting"),
        ("Intangible assets", "ASC 350", "US", "accounting"),
        ("Intangible assets", "IAS 38", "IFRS", "accounting"),
        ("Impairment", "ASC 360", "US", "accounting"),
        ("Impairment", "IAS 36", "IFRS", "accounting"),
        ("Financial instruments", "ASC 825", "US", "accounting"),
        ("Financial instruments", "IFRS 9", "IFRS", "accounting"),
        ("Income taxes", "ASC 740", "US", "accounting"),
        ("Income taxes", "IAS 12", "IFRS", "accounting"),
        ("Audit risk", "AU-C 315", "US", "auditing"),
        ("Audit risk", "ISA 315", "IFRS", "auditing"),
        ("Materiality", "AU-C 320", "US", "auditing"),
        ("Materiality", "ISA 320", "IFRS", "auditing"),
        ("Going concern", "AU-C 570", "US", "auditing"),
        ("Going concern", "ISA 570", "IFRS", "auditing"),
    ]
    for concept, standard, jur, corpus in pairs:
        c_id = f"c::{concept}"
        s_id = f"s::{standard}"
        _node(g, seen_n, Node(id=c_id, label=concept, type="concept"))
        _node(
            g, seen_n,
            Node(id=s_id, label=standard, type="standard", jurisdiction=jur, corpus_type=corpus),
        )
        _edge(g, seen_e, c_id, s_id, kind="references")
    # Equivalent-IFRS bridges between same-concept standards.
    by_concept: dict[str, list[str]] = {}
    for n in g.nodes:
        if n.type != "standard":
            continue
        for c_node in (x for x in g.nodes if x.type == "concept"):
            if any(e.source == c_node.id and e.target == n.id for e in g.edges):
                by_concept.setdefault(c_node.id, []).append(n.id)
    for c_id, std_ids in by_concept.items():
        if len(std_ids) == 2:
            _edge(g, seen_e, std_ids[0], std_ids[1], kind="equivalent")
    g.chunk_count = 0
    return g


# Caching --------------------------------------------------------------


_CACHE: dict[tuple, tuple[float, Graph]] = {}


async def build_graph(
    *,
    jurisdictions: list[str] | None = None,
    corpus_types: list[str] | None = None,
    max_nodes: int = 200,
    sample_size: int = 800,
    ttl_seconds: float = 60.0,
) -> Graph:
    key = (tuple(jurisdictions or ()), tuple(corpus_types or ()), max_nodes)
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and (now - hit[0]) < ttl_seconds:
        return hit[1]

    store = get_vector_store()
    chunks = await _gather_chunks(
        store, jurisdictions=jurisdictions, corpus_types=corpus_types, limit=sample_size
    )

    if not chunks:
        graph = _curated_graph()
        _CACHE[key] = (now, graph)
        return graph

    graph = Graph(chunk_count=len(chunks))
    seen_n: dict[str, Node] = {}
    seen_e: dict[tuple[str, str], Edge] = {}

    for c in chunks:
        for concept in _classify(c.text):
            c_id = f"c::{concept}"
            _node(graph, seen_n, Node(id=c_id, label=concept, type="concept"))
            if c.standard:
                s_id = f"s::{c.standard}"
                _node(
                    graph, seen_n,
                    Node(
                        id=s_id,
                        label=c.standard,
                        type="standard",
                        jurisdiction=c.jurisdiction,
                        corpus_type=c.corpus_type,
                        language=c.language,
                    ),
                )
                _edge(graph, seen_e, c_id, s_id, kind="references")
                if c.paragraph:
                    p_id = f"p::{c.standard}::{c.paragraph}"
                    _node(
                        graph, seen_n,
                        Node(
                            id=p_id,
                            label=c.paragraph,
                            type="paragraph",
                            jurisdiction=c.jurisdiction,
                            corpus_type=c.corpus_type,
                            language=c.language,
                            url=c.url,
                            excerpt=c.text[:300],
                        ),
                    )
                    _edge(graph, seen_e, s_id, p_id, kind="has")
        if len(graph.nodes) >= max_nodes:
            graph.truncated = True
            break

    _CACHE[key] = (now, graph)
    return graph


def clear_cache() -> None:
    _CACHE.clear()
