"""Unit tests for the citation validator."""

from __future__ import annotations

from app.domain.models import Chunk, RetrievedChunk
from app.rag.citation import validate_citations


def _chunk(text: str, *, url: str = "https://x.test/a", standard: str = "ASC 606-10-25-1") -> Chunk:
    return Chunk(
        source_id="fixture",
        standard=standard,
        paragraph="25-1",
        jurisdiction="US",
        corpus_type="accounting",
        language="en",
        url=url,
        text=text,
        content_sha1="dead",
    )


def test_quote_present_passes() -> None:
    rc = [RetrievedChunk(chunk=_chunk("Revenue is recognized when control transfers to the customer."), score=0.9)]
    raw = [{"standard": "ASC 606-10-25-1", "paragraph": "25-1", "url": "https://x.test/a", "quote": "control transfers to the customer"}]
    res = validate_citations(raw, rc)
    assert len(res.kept) == 1
    assert not res.dropped_reasons


def test_quote_absent_dropped() -> None:
    rc = [RetrievedChunk(chunk=_chunk("Revenue is recognized."), score=0.9)]
    raw = [{"standard": "ASC 606-10-25-1", "url": "https://x.test/a", "quote": "this phrase is not in the chunk"}]
    res = validate_citations(raw, rc)
    assert res.kept == ()
    assert any("not found" in r for r in res.dropped_reasons)


def test_url_mismatch_and_standard_mismatch_dropped() -> None:
    rc = [RetrievedChunk(chunk=_chunk("Revenue is recognized.", url="https://x.test/a", standard="ASC 606"), score=0.9)]
    raw = [{"standard": "IFRS 15", "url": "https://other.test/b", "quote": "Revenue is recognized"}]
    res = validate_citations(raw, rc)
    assert res.kept == ()


def test_whitespace_insensitive_match() -> None:
    rc = [RetrievedChunk(chunk=_chunk("Revenue   is\nrecognized when control transfers."), score=0.9)]
    raw = [{"standard": "ASC 606-10-25-1", "url": "https://x.test/a", "quote": "Revenue is recognized when control transfers"}]
    res = validate_citations(raw, rc)
    assert len(res.kept) == 1


def test_empty_quote_dropped() -> None:
    rc = [RetrievedChunk(chunk=_chunk("anything"), score=0.9)]
    res = validate_citations([{"standard": "ASC 606", "url": "https://x.test/a", "quote": ""}], rc)
    assert res.kept == ()


def test_matches_by_standard_when_url_missing() -> None:
    rc = [RetrievedChunk(chunk=_chunk("Performance obligations are identified."), score=0.9)]
    raw = [{"standard": "ASC 606-10-25-1", "quote": "Performance obligations are identified"}]
    res = validate_citations(raw, rc)
    assert len(res.kept) == 1
