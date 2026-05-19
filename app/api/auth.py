"""Auth dependencies: extract the request principal from JWT or admin key."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.security import InvalidTokenError, decode_token
from app.config import get_settings
from app.db.models.auth_models import User, UserRole
from app.db.session import get_session


@dataclass(frozen=True)
class RequestPrincipal:
    user_id: uuid.UUID
    firm_id: uuid.UUID
    role: UserRole
    email: str
    is_admin: bool


async def _principal_from_token(
    authorization: str | None,
    session: AsyncSession,
) -> RequestPrincipal | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token, expected_type="access")
    except InvalidTokenError as exc:
        raise ApiError(status=401, code="invalid_token", detail=str(exc)) from exc

    try:
        user_id = uuid.UUID(payload.sub)
        firm_id = uuid.UUID(payload.firm_id)
    except (ValueError, TypeError) as exc:
        raise ApiError(status=401, code="invalid_token", detail="malformed claims") from exc

    user = await session.get(User, user_id)
    if user is None or user.firm_id != firm_id:
        raise ApiError(status=401, code="invalid_token", detail="user no longer exists")
    return RequestPrincipal(
        user_id=user.id,
        firm_id=user.firm_id,
        role=user.role,
        email=user.email,
        is_admin=user.role is UserRole.admin,
    )


async def _principal_from_api_key(
    api_key: str | None,
    session: AsyncSession,
) -> RequestPrincipal | None:
    if not api_key:
        return None
    settings = get_settings()
    if api_key == settings.admin_api_key.get_secret_value():
        # Admin key — no user row; synthetic principal for admin tooling.
        return RequestPrincipal(
            user_id=uuid.UUID(int=0),
            firm_id=uuid.UUID(int=0),
            role=UserRole.admin,
            email="admin@local",
            is_admin=True,
        )
    # Per-user API keys would go here once minted (Phase 9). Reject unknown.
    raise ApiError(status=401, code="invalid_api_key", detail="unknown API key")


async def current_principal(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session: AsyncSession = Depends(get_session),
) -> RequestPrincipal:
    """Resolve the request principal from Authorization or X-API-Key."""
    principal = await _principal_from_token(authorization, session)
    if principal is None:
        principal = await _principal_from_api_key(x_api_key, session)
    if principal is None:
        raise ApiError(status=401, code="unauthorized", detail="missing credentials")
    return principal


async def require_admin(
    principal: RequestPrincipal = Depends(current_principal),
) -> RequestPrincipal:
    if not principal.is_admin:
        raise ApiError(status=403, code="forbidden", detail="admin required")
    return principal


__all__ = [
    "RequestPrincipal",
    "current_principal",
    "require_admin",
]
