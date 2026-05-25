"""Per-source ingest-run history for the standards corpus.

Each row records one attempt to (re-)fetch a configured source from
``config/sources.yaml`` and embed it into the vector store. Newest row
per source_id is the authoritative 'last refreshed' indicator surfaced
in the Settings UI.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid


class StandardsIngestStatus(str, enum.Enum):
    # Names == values so SAEnum serialization matches the Postgres enum
    # values 1:1 (see CLAUDE.md §3 SQLAlchemy + enums).
    running = "running"
    done = "done"
    failed = "failed"


class StandardsIngestRun(Base, TimestampMixin):
    __tablename__ = "standards_ingest_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    source_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[StandardsIngestStatus] = mapped_column(
        SAEnum(StandardsIngestStatus, name="standards_ingest_status"),
        default=StandardsIngestStatus.running,
        nullable=False,
    )
    chunks_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
