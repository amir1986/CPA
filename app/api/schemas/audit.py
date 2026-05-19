"""Pydantic schemas for /analyze and /audit/*."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


# ──────────────── analyze ────────────────


class RatioOut(BaseModel):
    name: str
    period_end: date
    value: float | None
    numerator: float
    denominator: float


class RatioRunOut(BaseModel):
    period_end: date
    ratios: list[RatioOut]


class BenfordRunOut(BaseModel):
    observed: dict[int, int]
    observed_pct: dict[int, float]
    expected_pct: dict[int, float]
    chi_square: float
    n: int
    suspect: bool


# ──────────────── audit ────────────────


class SampleIn(BaseModel):
    method: Literal["random", "stratified", "mus"] = "random"
    size: int = Field(default=25, ge=1, le=2000)
    seed: int = 42
    performance_materiality: float | None = None
    strata_boundaries: list[float] | None = None
    per_stratum: int | None = None


class SampleOut(BaseModel):
    id: str
    method: str
    seed: int
    sample_size: int
    sample_ids: list[str]


class JETestIn(BaseModel):
    test_kind: Literal[
        "benford", "weekend_holiday", "round_amounts", "unusual_user", "late_postings", "threshold"
    ]
    amount_threshold: float | None = None
    units: int | None = 1000
    rare_threshold: int | None = 3
    max_lag_days: int | None = 5


class JETestHitOut(BaseModel):
    entry_id: str
    amount: float
    reason: str
    extra: dict | None = None


class JETestRunOut(BaseModel):
    id: str
    test_kind: str
    hits_count: int
    hits: list[JETestHitOut]


class WorkpaperIn(BaseModel):
    template: str
    title: str
    inputs: dict = Field(default_factory=dict)
    references: dict = Field(default_factory=dict)


class WorkpaperOut(BaseModel):
    id: str
    title: str
    type: str
    body_md: str
    pdf_s3_uri: str | None
    references: dict


class FindingIn(BaseModel):
    workpaper_id: str | None = None
    assertion: str | None = None
    risk_level: Literal["low", "medium", "high"] = "medium"
    description: str
    evidence_refs: dict = Field(default_factory=dict)


class FindingOut(BaseModel):
    id: str
    workpaper_id: str | None
    assertion: str | None
    risk_level: str
    description: str
    evidence_refs: dict
