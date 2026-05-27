"""Authentication endpoints: register, login, verify, reset, refresh, me."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import (
    RequestPrincipal,
    current_principal,
    current_principal_permissive,
)
from app.api.errors import ApiError
from app.api.schemas.auth import (
    LoginIn,
    LoginOut,
    MessageOut,
    RefreshIn,
    RegisterIn,
    ResetConfirmIn,
    ResetRequestIn,
    TokenPair,
    UserOut,
    VerifyIn,
)
from app.api.security import (
    InvalidTokenError,
    decode_token,
    email_tokens_equal,
    expiry,
    generate_email_token,
    hash_email_token,
    hash_password,
    issue_access_token,
    issue_refresh_token,
    verify_password,
)
from app.config import get_settings
from app.db.models.auth_models import (
    AuthToken,
    AuthTokenKind,
    Firm,
    User,
    UserRole,
)
from app.db.session import get_session
from app.email.sender import send_email

router = APIRouter(prefix="/auth", tags=["auth"])

VERIFY_TTL = 3600 * 24                  # 24 h
RESET_TTL = 3600 * 2                    # 2 h


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role.value,
        locale=user.locale,
        firm_id=str(user.firm_id),
        email_verified=user.email_verified_at is not None,
    )


def _tokens(user: User) -> TokenPair:
    return TokenPair(
        access_token=issue_access_token(
            user_id=str(user.id), firm_id=str(user.firm_id), role=user.role.value
        ),
        refresh_token=issue_refresh_token(
            user_id=str(user.id), firm_id=str(user.firm_id), role=user.role.value
        ),
    )


@router.post("/register", response_model=LoginOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterIn,
    session: AsyncSession = Depends(get_session),
) -> LoginOut:
    existing = await session.scalar(select(User).where(User.email == payload.email.lower()))
    if existing is not None:
        raise ApiError(status=409, code="email_taken", detail="that email is already registered")

    # New-firm self-serve path: caller supplies a firm_name. (Invite codes are
    # validated in Phase 5; for now an unknown code → 400.)
    if not payload.firm_name and not payload.firm_invite_code:
        raise ApiError(
            status=400,
            code="firm_required",
            detail="provide firm_name to create a new firm, or firm_invite_code to join one",
        )
    if payload.firm_invite_code:
        raise ApiError(status=400, code="invite_unsupported", detail="invite codes are not yet supported")

    firm = Firm(name=payload.firm_name.strip())  # type: ignore[union-attr]
    session.add(firm)
    await session.flush()

    user = User(
        firm_id=firm.id,
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role=UserRole.admin,  # first user of a new firm is admin
        name=payload.name,
    )
    session.add(user)
    await session.flush()

    plaintext, digest = generate_email_token()
    token_row = AuthToken(
        user_id=user.id,
        kind=AuthTokenKind.verify_email,
        token_hash=digest,
        expires_at=expiry(VERIFY_TTL),
        created_at=datetime.now(tz=UTC),
    )
    session.add(token_row)
    await session.flush()

    settings = get_settings()
    verify_link = f"{_app_base(settings)}/verify?token={plaintext}"
    await send_email(
        to=user.email,
        subject="Verify your CPA AI Assistant account",
        body=f"Welcome! Confirm your email here:\n\n{verify_link}\n\nThis link expires in 24h.",
    )

    return LoginOut(tokens=_tokens(user), user=_user_out(user))


@router.post("/login", response_model=LoginOut)
async def login(
    payload: LoginIn,
    session: AsyncSession = Depends(get_session),
) -> LoginOut:
    user = await session.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise ApiError(status=401, code="invalid_credentials", detail="email or password is incorrect")
    user.last_login_at = datetime.now(tz=UTC)
    await session.flush()
    return LoginOut(tokens=_tokens(user), user=_user_out(user))


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    payload: RefreshIn,
    session: AsyncSession = Depends(get_session),
) -> TokenPair:
    try:
        claims = decode_token(payload.refresh_token, expected_type="refresh")
    except InvalidTokenError as exc:
        raise ApiError(status=401, code="invalid_token", detail=str(exc)) from exc
    user = await session.get(User, claims.sub)
    if user is None:
        raise ApiError(status=401, code="invalid_token", detail="user no longer exists")
    return _tokens(user)


@router.post("/verify", response_model=MessageOut)
async def verify(
    payload: VerifyIn,
    session: AsyncSession = Depends(get_session),
) -> MessageOut:
    digest = hash_email_token(payload.token)
    row = await session.scalar(
        select(AuthToken).where(
            AuthToken.token_hash == digest,
            AuthToken.kind == AuthTokenKind.verify_email,
        )
    )
    if row is None or row.used_at is not None or row.expires_at < datetime.now(tz=UTC):
        raise ApiError(status=400, code="invalid_token", detail="link is invalid or expired")
    if not email_tokens_equal(row.token_hash, digest):
        raise ApiError(status=400, code="invalid_token", detail="link is invalid or expired")

    user = await session.get(User, row.user_id)
    if user is None:
        raise ApiError(status=400, code="invalid_token", detail="user no longer exists")
    user.email_verified_at = datetime.now(tz=UTC)
    row.used_at = datetime.now(tz=UTC)
    return MessageOut(detail="email verified")


@router.post("/reset/request", response_model=MessageOut)
async def reset_request(
    payload: ResetRequestIn,
    session: AsyncSession = Depends(get_session),
) -> MessageOut:
    # Always 200 — don't leak whether an email exists.
    user = await session.scalar(select(User).where(User.email == payload.email.lower()))
    if user is not None:
        plaintext, digest = generate_email_token()
        session.add(
            AuthToken(
                user_id=user.id,
                kind=AuthTokenKind.password_reset,
                token_hash=digest,
                expires_at=expiry(RESET_TTL),
                created_at=datetime.now(tz=UTC),
            )
        )
        await session.flush()
        settings = get_settings()
        link = f"{_app_base(settings)}/reset?token={plaintext}"
        await send_email(
            to=user.email,
            subject="Reset your CPA AI Assistant password",
            body=f"Reset link (expires in 2h):\n\n{link}",
        )
    return MessageOut(detail="if that email exists, we sent a reset link")


@router.post("/reset/confirm", response_model=MessageOut)
async def reset_confirm(
    payload: ResetConfirmIn,
    session: AsyncSession = Depends(get_session),
) -> MessageOut:
    digest = hash_email_token(payload.token)
    row = await session.scalar(
        select(AuthToken).where(
            AuthToken.token_hash == digest,
            AuthToken.kind == AuthTokenKind.password_reset,
        )
    )
    if row is None or row.used_at is not None or row.expires_at < datetime.now(tz=UTC):
        raise ApiError(status=400, code="invalid_token", detail="link is invalid or expired")
    user = await session.get(User, row.user_id)
    if user is None:
        raise ApiError(status=400, code="invalid_token", detail="user no longer exists")
    user.password_hash = hash_password(payload.new_password)
    row.used_at = datetime.now(tz=UTC)
    return MessageOut(detail="password updated")


@router.get("/me", response_model=UserOut)
async def me(
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    user = await session.get(User, principal.user_id)
    if user is None:
        raise ApiError(status=401, code="invalid_token", detail="user no longer exists")
    return _user_out(user)


class LocalePatchIn(BaseModel):
    locale: str   # "en" or "he"


@router.patch("/me/locale", response_model=UserOut)
async def update_locale(
    payload: LocalePatchIn,
    # Permissive: browser-side PATCH from /settings/profile goes through
    # the bare /api/* Next rewrite which strips the bearer token, so the
    # strict current_principal would 401 every Save click. Locale is a
    # benign per-user preference; the worst case of a demo-user collapse
    # here is "the demo user's stored locale changes" — the cookie still
    # drives each browser's actual UI direction.
    principal: RequestPrincipal = Depends(current_principal_permissive),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    if payload.locale not in ("en", "he"):
        raise ApiError(status=400, code="bad_request", detail="locale must be 'en' or 'he'")
    user = await session.get(User, principal.user_id)
    if user is None:
        raise ApiError(status=401, code="invalid_token", detail="user no longer exists")
    user.locale = payload.locale
    await session.flush()
    return _user_out(user)


def _app_base(settings) -> str:  # type: ignore[no-untyped-def]
    # AUTH_URL is the user-visible host; falls back to localhost for dev.
    import os
    return os.environ.get("AUTH_URL", "http://localhost:8080")
