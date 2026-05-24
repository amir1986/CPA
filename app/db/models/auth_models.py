"""Firms, users, tweaks, auth tokens."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_uuid


class UserRole(str, enum.Enum):
    partner = "partner"
    manager = "manager"
    senior = "senior"
    staff = "staff"
    admin = "admin"


class AuthTokenKind(str, enum.Enum):
    verify_email = "verify_email"
    password_reset = "password_reset"


class Firm(Base, TimestampMixin):
    __tablename__ = "firms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    default_jurisdiction: Mapped[str | None] = mapped_column(String(8), nullable=True)
    base_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)

    users: Mapped[list[User]] = relationship(back_populates="firm")


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("firms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole, name="user_role"), default=UserRole.staff, nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    locale: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    api_key_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    firm: Mapped[Firm] = relationship(back_populates="users")
    tweaks: Mapped[UserTweaks | None] = relationship(back_populates="user", uselist=False)


class UserTweaks(Base, TimestampMixin):
    __tablename__ = "user_tweaks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    top_k: Mapped[int | None] = mapped_column(nullable=True)
    min_score: Mapped[float | None] = mapped_column(nullable=True)
    lang_strict: Mapped[bool | None] = mapped_column(nullable=True)
    ratio_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sampling_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    user: Mapped[User] = relationship(back_populates="tweaks")


class AuthToken(Base):
    """Single-use tokens for email verification and password reset."""

    __tablename__ = "auth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[AuthTokenKind] = mapped_column(SAEnum(AuthTokenKind, name="auth_token_kind"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
