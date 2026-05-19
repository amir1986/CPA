"""Bank statements and reconciliations."""

from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import Date, Enum as SAEnum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid


class ReconciliationKind(str, enum.Enum):
    bank = "bank"
    intercompany = "intercompany"


class BankStatement(Base, TimestampMixin):
    __tablename__ = "bank_statements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id", ondelete="SET NULL"), nullable=True
    )
    statement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    line_no: Mapped[int | None] = mapped_column(nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    balance: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    matched_je_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gl_entries.id", ondelete="SET NULL"), nullable=True
    )
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )


class Reconciliation(Base, TimestampMixin):
    __tablename__ = "reconciliations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[ReconciliationKind] = mapped_column(SAEnum(ReconciliationKind, name="reconciliation_kind"), nullable=False)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
