"""Audit-side entities: samples, JE tests, three-way matches, programs, workpapers, findings."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid


class Sample(Base, TimestampMixin):
    __tablename__ = "samples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    population_query: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sample_size: Mapped[int] = mapped_column(nullable=False)
    sample_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    seed: Mapped[int] = mapped_column(nullable=False)
    performance_materiality: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    drawn_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JETestRun(Base, TimestampMixin):
    __tablename__ = "je_test_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_kind: Mapped[str] = mapped_column(String(48), nullable=False)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    hits_count: Mapped[int] = mapped_column(nullable=False, default=0)
    hits: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ran_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class ThreeWayMatch(Base, TimestampMixin):
    __tablename__ = "three_way_matches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    results_summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    exceptions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditProgram(Base, TimestampMixin):
    __tablename__ = "audit_programs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    area: Mapped[str] = mapped_column(String(64), nullable=False)
    procedures: Mapped[list] = mapped_column(JSONB, nullable=False)


class Workpaper(Base, TimestampMixin):
    __tablename__ = "workpapers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body_md: Mapped[str] = mapped_column(nullable=False)
    pdf_s3_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    references: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    prepared_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class AuditFinding(Base, TimestampMixin):
    __tablename__ = "audit_findings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workpaper_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workpapers.id", ondelete="SET NULL"), nullable=True
    )
    assertion: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    description: Mapped[str] = mapped_column(nullable=False)
    evidence_refs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
