"""Chart of accounts, GL entries, trial balances, categorization mappings."""

from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid


class AccountType(str, enum.Enum):
    asset = "asset"
    liability = "liability"
    equity = "equity"
    revenue = "revenue"
    expense = "expense"


class ChartOfAccount(Base, TimestampMixin):
    __tablename__ = "chart_of_accounts"
    __table_args__ = (
        UniqueConstraint("engagement_id", "code", name="uq_chart_of_accounts_engagement_id_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[AccountType] = mapped_column(SAEnum(AccountType, name="account_type"), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id", ondelete="SET NULL"), nullable=True
    )
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)


class GLEntry(Base, TimestampMixin):
    __tablename__ = "gl_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chart_of_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    je_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    je_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    posting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    debit: Mapped[float] = mapped_column(Numeric(20, 4), default=0, nullable=False)
    credit: Mapped[float] = mapped_column(Numeric(20, 4), default=0, nullable=False)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    fx_rate: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    document_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preparer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approver: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )


class TrialBalance(Base, TimestampMixin):
    __tablename__ = "trial_balances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id", ondelete="SET NULL"), nullable=True
    )
    account_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    opening: Mapped[float] = mapped_column(Numeric(20, 4), default=0, nullable=False)
    debit_total: Mapped[float] = mapped_column(Numeric(20, 4), default=0, nullable=False)
    credit_total: Mapped[float] = mapped_column(Numeric(20, 4), default=0, nullable=False)
    closing: Mapped[float] = mapped_column(Numeric(20, 4), default=0, nullable=False)
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )


class CoaMapping(Base, TimestampMixin):
    __tablename__ = "coa_mappings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule: Mapped[dict] = mapped_column(JSONB, nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), default=0, nullable=False)
    learned_from_count: Mapped[int] = mapped_column(default=0, nullable=False)
