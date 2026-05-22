"""Knowledge-graph builder tests."""

from __future__ import annotations

import pytest

from app.domain.models import Chunk
from app.rag.knowledge_graph import build_graph, clear_cache
from app.rag.vector_store import CPA_KNOWLEDGE, MemoryVectorStore, StoredPoint, reset_vector_store


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CPA_VECTOR_BACKEND", "memory")
    reset_vector_store()
    clear_cache()
    yield
    reset_vector_store()
    clear_cache()


def _store_with(chunks: list[Chunk]) -> MemoryVectorStore:
    store = MemoryVectorStore()
    for i, c in enumerate(chunks):
        store._collections.setdefault(CPA_KNOWLEDGE, {})[f"p{i}"] = StoredPoint(  # type: ignore[attr-defined]
            id=f"p{i}", embedding=[0.0] * 8, chunk=c
        )
    return store


def _chunk(text: str, *, standard: str | None = None, paragraph: str | None = None, jur: str = "US", corpus: str = "accounting", lang: str = "en") -> Chunk:
    return Chunk(
        source_id="t",
        standard=standard,
        paragraph=paragraph,
        jurisdiction=jur,
        corpus_type=corpus,
        language=lang,
        url=f"https://x.test/{standard or 'p'}",
        text=text,
        content_sha1="x",
    )


@pytest.mark.asyncio
async def test_empty_corpus_returns_curated_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    g = await build_graph()
    # Curated bridges should be present.
    labels = {n.label for n in g.nodes}
    assert {"Revenue recognition", "ASC 606", "IFRS 15"} <= labels
    # ASC 606 ↔ IFRS 15 equivalent edge
    eq = [e for e in g.edges if e.kind == "equivalent"]
    assert any({e.source, e.target} >= {"s::ASC 606", "s::IFRS 15"} for e in eq)


@pytest.mark.asyncio
async def test_corpus_concepts_inferred_from_text(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store_with([
        _chunk("Revenue recognition is governed by ASC 606.", standard="ASC 606-10-25-1", paragraph="25-1"),
        _chunk("Lease accounting under IFRS 16 requires right-of-use assets.", standard="IFRS 16.1", paragraph="1", jur="IFRS"),
    ])
    monkeypatch.setattr("app.rag.knowledge_graph.get_vector_store", lambda: store)

    g = await build_graph()
    labels = {n.label for n in g.nodes}
    assert "Revenue recognition" in labels
    assert "Leases" in labels
    assert "ASC 606-10-25-1" in labels
    # Concept → standard edge
    e = [e for e in g.edges if e.source == "c::Revenue recognition" and e.target == "s::ASC 606-10-25-1"]
    assert e and e[0].kind == "references"


@pytest.mark.asyncio
async def test_jurisdiction_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store_with([
        _chunk("Revenue recognition under ASC 606.", standard="ASC 606", jur="US"),
        _chunk("Revenue recognition under IFRS 15.", standard="IFRS 15", jur="IFRS"),
    ])
    monkeypatch.setattr("app.rag.knowledge_graph.get_vector_store", lambda: store)
    g = await build_graph(jurisdictions=["US"])
    standards = {n.label for n in g.nodes if n.type == "standard"}
    assert "ASC 606" in standards
    assert "IFRS 15" not in standards


@pytest.mark.asyncio
async def test_max_nodes_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [
        _chunk(f"Revenue recognition note {i}.", standard=f"ASC 606-{i}", paragraph=str(i))
        for i in range(50)
    ]
    monkeypatch.setattr("app.rag.knowledge_graph.get_vector_store", lambda: _store_with(chunks))
    g = await build_graph(max_nodes=10)
    assert g.truncated is True
    # Each chunk can add up to 3 nodes (concept + standard + paragraph), so
    # the budget can be exceeded by one chunk's worth of nodes.
    assert len(g.nodes) <= 13
