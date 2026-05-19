"""Clients and engagements."""

from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import Date, Enum as SAEnum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_uuid


class EngagementType(str, enum.Enum):
    audit = "audit"
    review = "review"
    compilation = "compilation"
    tax = "tax"
    bookkeeping = "bookkeeping"


class EngagementStatus(str, enum.Enum):
    planning = "planning"
    fieldwork = "fieldwork"
    review = "review"
    signed_off = "signed_off"
    archived = "archived"


class Client(Base, TimestampMixin):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("firms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(String(8), nullable=True)
    base_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    fy_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    engagements: Mapped[list["Engagement"]] = relationship(back_populates="client")


class Engagement(Base, TimestampMixin):
    __tablename__ = "engagements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[EngagementType] = mapped_column(SAEnum(EngagementType, name="engagement_type"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    materiality: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    performance_materiality: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    status: Mapped[EngagementStatus] = mapped_column(
        SAEnum(EngagementStatus, name="engagement_status"), default=EngagementStatus.planning, nullable=False
    )

    client: Mapped[Client] = relationship(back_populates="engagements")
