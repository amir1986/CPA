"""Schemas for /agent and /agent traces."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    max_steps: int = Field(default=6, ge=1, le=12)


class ToolCallOut(BaseModel):
    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None


class AgentRunOut(BaseModel):
    id: str
    request: str
    final_answer: str | None
    citations: list[dict[str, Any]]
    tool_calls: list[ToolCallOut]
    created_at: datetime
