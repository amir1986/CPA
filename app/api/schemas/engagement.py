"""Pydantic schemas for clients, engagements, and files."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    jurisdiction: str | None = Field(default=None, max_length=8)
    base_currency: str | None = Field(default=None, max_length=8)
    fy_end: date | None = None


class ClientOut(BaseModel):
    id: str
    name: str
    jurisdiction: str | None
    base_currency: str | None
    fy_end: date | None
    created_at: datetime


class EngagementIn(BaseModel):
    client_id: str
    name: str = Field(min_length=1, max_length=200)
    type: Literal["audit", "review", "compilation", "tax", "bookkeeping"]
    period_start: date | None = None
    period_end: date | None = None
    materiality: float | None = None
    performance_materiality: float | None = None


class EngagementOut(BaseModel):
    id: str
    client_id: str
    name: str
    type: str
    period_start: date | None
    period_end: date | None
    materiality: float | None
    performance_materiality: float | None
    status: str
    created_at: datetime


class FileOut(BaseModel):
    id: str
    engagement_id: str
    kind: str
    original_name: str
    s3_uri: str
    sha256: str
    mime: str | None
    size: int
    parsed_status: str
    parsed_summary: dict | None
    created_at: datetime


class FileListOut(BaseModel):
    items: list[FileOut]
    total: int
