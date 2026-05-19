"""Domain dataclasses shared across services (RAG, agent, audit, …).

These are NOT pydantic schemas (those live in app/api/schemas) and not
SQLAlchemy models (those live in app/db/models). They model in-process
values: retrieved chunks, citations, ratio results, JE-test hits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class Chunk:
    """A normalized, embeddable piece of source text."""

    source_id: str
    standard: str | None       # e.g. "ASC 606-10-25-1", "IFRS 15.31"
    paragraph: str | None
    jurisdiction: str          # e.g. "US", "IFRS", "IL"
    corpus_type: str           # "accounting" | "auditing" | "tax"
    language: str              # "en" | "he"
    url: str
    text: str
    content_sha1: str
    fetched_at: datetime | None = None


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class Citation:
    standard: str | None
    paragraph: str | None
    url: str
    quote: str

    def triple(self) -> tuple[str | None, str | None, str]:
        return (self.standard, self.paragraph, self.url)


@dataclass(frozen=True)
class RatioResult:
    name: str
    period_end: date
    value: float | None
    numerator: float
    denominator: float
    inputs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JETestHit:
    entry_id: str
    je_number: str | None
    je_date: date | None
    amount: float
    reason: str
    extra: dict[str, Any] = field(default_factory=dict)
