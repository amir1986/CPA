"""End-to-end test of the cited-Q&A pipeline with FakeLLM + MemoryVectorStore."""

from __future__ import annotations

import json

import pytest

from app.embeddings import reset_embedder
from app.ingest_standards.pipeline import FetchedDocument, ingest_source
from app.ingest_standards.registry import Source
from app.llm.client import FakeLLM
from app.rag.query_engine import answer_question
from app.rag.vector_store import reset_vector_store


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CPA_VECTOR_BACKEND", "memory")
    monkeypatch.setenv("CPA_EMBED_BACKEND", "hash")
    monkeypatch.setenv("CPA_LLM_BACKEND", "fake")
    reset_vector_store()
    reset_embedder()
    yield
    reset_vector_store()
    reset_embedder()


SOURCE = Source(
    id="fixture_asc",
    name="Fixture ASC excerpt",
    url="https://x.test/asc606",
    corpus_type="accounting",
    jurisdiction="US",
    language="en",
    kind="html",
    licence="fixture",
)

TEXT = (
    "Revenue is recognized when control of the promised goods or services "
    "transfers to the customer. The five steps under ASC 606 are: identify "
    "the contract, identify performance obligations, determine the "
    "transaction price, allocate the transaction price, and recognize "
    "revenue when (or as) performance obligations are satisfied."
)


async def _seed_corpus() -> None:
    async def fetch(_: Source) -> list[FetchedDocument]:
        return [FetchedDocument(url=SOURCE.url, text=TEXT, standard="ASC 606-10-25-1", paragraph="25-1")]

    n = await ingest_source(SOURCE, fetcher=fetch)
    assert n > 0


@pytest.mark.asyncio
async def test_grounded_question_returns_cited_answer() -> None:
    await _seed_corpus()
    fake = FakeLLM()
    fake.set_response(json.dumps({
        "answer": "Recognize revenue when control transfers to the customer.",
        "citations": [{
            "standard": "ASC 606-10-25-1",
            "paragraph": "25-1",
            "url": SOURCE.url,
            "quote": "control of the promised goods or services transfers to the customer",
        }],
    }))

    result = await answer_question("When is revenue recognized?", llm=fake)
    assert result.refused is False
    assert "Recognize revenue" in result.answer
    assert len(result.citations) == 1
    assert result.citations[0].url == SOURCE.url


@pytest.mark.asyncio
async def test_ungrounded_question_refuses() -> None:
    await _seed_corpus()
    fake = FakeLLM()
    fake.set_response(json.dumps({"answer": "something", "citations": []}))

    # The hash embedder + tiny corpus will return a low-score top match.
    result = await answer_question(
        "What is the optimal seating chart for a thanksgiving dinner with 12 guests?",
        min_score=0.95,
        llm=fake,
    )
    assert result.refused is True
    assert "can't answer" in result.answer.lower() or "לא ניתן" in result.answer


@pytest.mark.asyncio
async def test_hallucinated_citation_dropped_and_refuses() -> None:
    await _seed_corpus()
    fake = FakeLLM()
    fake.set_response(json.dumps({
        "answer": "Hallucinated.",
        "citations": [{
            "standard": "ASC 606-10-25-1",
            "url": SOURCE.url,
            "quote": "this text is nowhere in the chunk",
        }],
    }))
    result = await answer_question("When is revenue recognized?", llm=fake)
    assert result.refused is True
    assert result.citations == []


@pytest.mark.asyncio
async def test_jurisdiction_filter() -> None:
    await _seed_corpus()
    fake = FakeLLM()
    fake.set_response(json.dumps({"answer": "x", "citations": []}))
    # Filtering to IL when only US is in the corpus must yield a refusal.
    result = await answer_question("Revenue recognition?", jurisdictions=["IL"], llm=fake)
    assert result.refused is True
    assert result.retrieved == []
