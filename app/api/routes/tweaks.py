"""/tweaks/me — per-user runtime overrides surfaced in the Tweaks panel."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import RequestPrincipal, current_principal
from app.api.errors import ApiError
from app.api.schemas.books import TweaksIn, TweaksOut
from app.db.models.auth_models import UserTweaks
from app.db.session import get_session

router = APIRouter(prefix="/tweaks", tags=["tweaks"])


def _out(t: UserTweaks | None) -> TweaksOut:
    if t is None:
        return TweaksOut(
            top_k=None, min_score=None, lang_strict=None,
            ratio_overrides=None, sampling_overrides=None,
        )
    return TweaksOut(
        top_k=t.top_k,
        min_score=t.min_score,
        lang_strict=t.lang_strict,
        ratio_overrides=t.ratio_overrides,
        sampling_overrides=t.sampling_overrides,
    )


@router.get("/me", response_model=TweaksOut)
async def get_tweaks(
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> TweaksOut:
    if principal.user_id.int == 0:
        raise ApiError(status=400, code="bad_request", detail="admin key has no per-user tweaks")
    t = await session.get(UserTweaks, principal.user_id)
    return _out(t)


@router.patch("/me", response_model=TweaksOut)
async def patch_tweaks(
    payload: TweaksIn,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> TweaksOut:
    if principal.user_id.int == 0:
        raise ApiError(status=400, code="bad_request", detail="admin key has no per-user tweaks")
    t = await session.get(UserTweaks, principal.user_id)
    if t is None:
        t = UserTweaks(user_id=principal.user_id, updated_at=datetime.now(tz=UTC))
        session.add(t)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(t, k, v)
    t.updated_at = datetime.now(tz=UTC)
    await session.flush()
    return _out(t)
