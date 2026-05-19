"""Schemas for /query and /sources."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CitationOut(BaseModel):
    standard: str | None
    paragraph: str | None
    url: str
    quote: str


class QueryIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    jurisdictions: list[str] | None = None
    corpus_types: list[str] | None = None
    top_k: int | None = Field(default=None, ge=1, le=32)
    min_score: float | None = Field(default=None, ge=0, le=1)


class RetrievedOut(BaseModel):
    standard: str | None
    paragraph: str | None
    url: str
    jurisdiction: str
    corpus_type: str
    language: str
    score: float


class QueryOut(BaseModel):
    answer: str
    citations: list[CitationOut]
    refused: bool
    language: str
    retrieved: list[RetrievedOut]


class SourceOut(BaseModel):
    id: str
    name: str
    url: str
    corpus_type: str
    jurisdiction: str
    language: str
    licence: str
