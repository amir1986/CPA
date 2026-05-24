"""USGAAP <> IFRS comparison runs and per-issue results.

Each run sits inside a hidden per-user engagement (type=comparisons). The
existing files table holds the uploaded source documents; we just keep
the higher-level analysis state here.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid


class ComparisonStatus(str, enum.Enum):
    parsing = "parsing"
    detecting = "detecting"
    comparing = "comparing"
    done = "done"
    failed = "failed"


class Framework(str, enum.Enum):
    us_gaap = "US"
    ifrs = "IFRS"


class ComparisonRun(Base, TimestampMixin):
    __tablename__ = "comparison_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("engagements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    status: Mapped[ComparisonStatus] = mapped_column(
        SAEnum(ComparisonStatus, name="comparison_status"),
        default=ComparisonStatus.parsing,
        nullable=False,
    )
    detected_framework: Mapped[Framework | None] = mapped_column(
        SAEnum(Framework, name="comparison_framework"), nullable=True
    )
    override_framework: Mapped[Framework | None] = mapped_column(
        SAEnum(Framework, name="comparison_framework", create_type=False), nullable=True
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class ComparisonIssue(Base, TimestampMixin):
    __tablename__ = "comparison_issues"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("comparison_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    current_summary: Mapped[str] = mapped_column(Text, nullable=False)
    current_user_cites: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    gaap_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    gaap_citations: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    ifrs_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ifrs_citations: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    differences: Mapped[str | None] = mapped_column(Text, nullable=True)
    conversion_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
