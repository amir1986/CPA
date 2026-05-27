"""Schemas for /coa, /gl, /trial-balance, /categorize."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class CoaAccountIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    type: Literal["asset", "liability", "equity", "revenue", "expense"]
    parent_code: str | None = None
    currency: str | None = None
    active: bool = True


class CoaAccountOut(BaseModel):
    id: str
    code: str
    name: str
    type: str
    parent_id: str | None
    currency: str | None
    active: bool


class CoaImportIn(BaseModel):
    template: str = Field(description="One of: us_gaap, ifrs, il_gaap")


class CoaImportOut(BaseModel):
    imported: int


class GLEntryOut(BaseModel):
    id: str
    je_number: str | None
    je_date: date | None
    posting_date: date | None
    account_id: str | None
    debit: float
    credit: float
    currency: str | None
    description: str | None
    preparer: str | None
    approver: str | None


class GLListOut(BaseModel):
    items: list[GLEntryOut]
    total: int


class TrialBalanceOut(BaseModel):
    id: str
    period_end: date
    account_id: str | None
    account_code: str | None
    account_name: str | None
    opening: float
    debit_total: float
    credit_total: float
    closing: float


class CategorizeRunIn(BaseModel):
    only_unmatched: bool = True


class CategorizeSuggestionOut(BaseModel):
    entry_id: str
    account_id: str
    confidence: float
    source: str
    rule_id: str | None = None
    rationale: str | None = None


class CategorizeRunOut(BaseModel):
    suggestions: list[CategorizeSuggestionOut]
    unmatched: int


class TweaksOut(BaseModel):
    top_k: int | None
    min_score: float | None
    lang_strict: bool | None
    ratio_overrides: dict | None
    sampling_overrides: dict | None


class TweaksIn(BaseModel):
    top_k: int | None = None
    min_score: float | None = None
    lang_strict: bool | None = None
    ratio_overrides: dict | None = None
    sampling_overrides: dict | None = None
