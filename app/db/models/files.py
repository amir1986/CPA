"""Uploaded files (TBs, GLs, bank statements, invoices, contracts, …)."""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import BigInteger, Enum as SAEnum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid


class FileKind(str, enum.Enum):
    trial_balance = "trial_balance"
    gl = "gl"
    bank = "bank"
    invoice = "invoice"
    financial_statements = "financial_statements"
    contract = "contract"
    policy = "policy"
    other = "other"


class ParsedStatus(str, enum.Enum):
    queued = "queued"
    extracting = "extracting"
    canonicalizing = "canonicalizing"
    done = "done"
    failed = "failed"


class File(Base, TimestampMixin):
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[FileKind] = mapped_column(SAEnum(FileKind, name="file_kind"), nullable=False)
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    s3_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mime: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parsed_status: Mapped[ParsedStatus] = mapped_column(
        SAEnum(ParsedStatus, name="parsed_status"), default=ParsedStatus.queued, nullable=False
    )
    parsed_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
