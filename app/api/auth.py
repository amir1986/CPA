"""Auth dependencies: extract the request principal from JWT or admin key."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header
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
    """Resolve the request principal.

    Login was removed (commit 'feat(auth): drop login flow — every request
    resolves to the shared demo user'), so every request — whether or not
    it carries an Authorization or X-API-Key — falls through to the demo
    user. The strict-mode resolution (real JWT, real API key) is still
    tried first so any pre-existing client with credentials keeps working.
    """
    principal = await _principal_from_token(authorization, session)
    if principal is None:
        principal = await _principal_from_api_key(x_api_key, session)
    if principal is None:
        principal = await _principal_for_demo_user(session)
    if principal is None:
        raise ApiError(
            status=503,
            code="demo_user_unavailable",
            detail="demo user has not been provisioned — api startup hook should have created it",
        )
    return principal


# Email of the shared "Skip → Demo User" account created by the web login
# page. Kept in lockstep with web/src/app/(auth)/login/page.tsx::SKIP_EMAIL.
DEMO_USER_EMAIL = "demo@cpa.example"


async def _principal_for_demo_user(session: AsyncSession) -> RequestPrincipal | None:
    """Resolve the canonical Skip-Demo user, treating it as admin.

    Returns None if the demo user hasn't been created yet (the very first
    Skip click on a fresh deploy registers it, so this is rare).
    """
    from sqlalchemy import select

    res = await session.execute(select(User).where(User.email == DEMO_USER_EMAIL))
    user = res.scalar_one_or_none()
    if user is None:
        try:
            from app.services.demo_bootstrap import ensure_demo_user_exists

            await ensure_demo_user_exists()
        except Exception:
            return None
        res = await session.execute(select(User).where(User.email == DEMO_USER_EMAIL))
        user = res.scalar_one_or_none()
    if user is None:
        return None
    return RequestPrincipal(
        user_id=user.id,
        firm_id=user.firm_id,
        role=UserRole.admin,           # Demo user is treated as admin everywhere.
        email=user.email,
        is_admin=True,
    )


async def current_principal_permissive(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session: AsyncSession = Depends(get_session),
) -> RequestPrincipal:
    """Like ``current_principal``, but falls back to the demo user when no
    credentials are presented.

    Used by routes that the deployed web tier hits from the browser via the
    bare Next.js ``rewrites()`` proxy, which can't inject an Authorization
    header. Authenticated requests still resolve to the real user — the demo
    fallback only kicks in when both Authorization and X-API-Key are absent.
    """
    principal = await _principal_from_token(authorization, session)
    if principal is None:
        principal = await _principal_from_api_key(x_api_key, session)
    if principal is None:
        principal = await _principal_for_demo_user(session)
    if principal is None:
        raise ApiError(
            status=401,
            code="unauthorized",
            detail="missing credentials and demo user not provisioned",
        )
    return principal


async def require_admin(
    principal: RequestPrincipal = Depends(current_principal),
) -> RequestPrincipal:
    if not principal.is_admin:
        raise ApiError(status=403, code="forbidden", detail="admin required")
    return principal


__all__ = [
    "DEMO_USER_EMAIL",
    "RequestPrincipal",
    "current_principal",
    "current_principal_permissive",
    "require_admin",
]
