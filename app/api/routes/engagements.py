"""Engagement CRUD — scoped to the principal's firm via the parent client."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import RequestPrincipal, current_principal
from app.api.errors import ApiError
from app.api.schemas.engagement import EngagementIn, EngagementOut
from app.db.models.engagement import Client, Engagement, EngagementType
from app.db.session import get_session

router = APIRouter(prefix="/engagements", tags=["engagements"])


def _out(e: Engagement) -> EngagementOut:
    return EngagementOut(
        id=str(e.id),
        client_id=str(e.client_id),
        name=e.name,
        type=e.type.value,
        period_start=e.period_start,
        period_end=e.period_end,
        materiality=float(e.materiality) if e.materiality is not None else None,
        performance_materiality=float(e.performance_materiality) if e.performance_materiality is not None else None,
        status=e.status.value,
        created_at=e.created_at,
    )


async def _ensure_in_firm(
    engagement_id: uuid.UUID,
    principal: RequestPrincipal,
    session: AsyncSession,
) -> Engagement:
    """Common multi-tenant check: 404 if the engagement isn't ours."""
    e = await session.get(Engagement, engagement_id)
    if e is None:
        raise ApiError(status=404, code="not_found", detail="engagement not found")
    c = await session.get(Client, e.client_id)
    if c is None or c.firm_id != principal.firm_id:
        raise ApiError(status=404, code="not_found", detail="engagement not found")
    return e


@router.get("", response_model=list[EngagementOut])
async def list_engagements(
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> list[EngagementOut]:
    # Join through clients to filter by firm.
    rows = (
        await session.scalars(
            select(Engagement)
            .join(Client, Client.id == Engagement.client_id)
            .where(Client.firm_id == principal.firm_id)
            .order_by(Engagement.created_at.desc())
        )
    ).all()
    return [_out(e) for e in rows]


@router.post("", response_model=EngagementOut, status_code=status.HTTP_201_CREATED)
async def create_engagement(
    payload: EngagementIn,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> EngagementOut:
    try:
        client_id = uuid.UUID(payload.client_id)
    except ValueError as exc:
        raise ApiError(status=400, code="bad_request", detail="client_id is not a UUID") from exc
    c = await session.get(Client, client_id)
    if c is None or c.firm_id != principal.firm_id:
        raise ApiError(status=404, code="not_found", detail="client not found")

    e = Engagement(
        client_id=client_id,
        name=payload.name,
        type=EngagementType(payload.type),
        period_start=payload.period_start,
        period_end=payload.period_end,
        materiality=payload.materiality,
        performance_materiality=payload.performance_materiality,
    )
    session.add(e)
    await session.flush()
    return _out(e)


@router.get("/{engagement_id}", response_model=EngagementOut)
async def get_engagement(
    engagement_id: uuid.UUID,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> EngagementOut:
    e = await _ensure_in_firm(engagement_id, principal, session)
    return _out(e)


# Re-export the helper so other routers can reuse the check.
ensure_in_firm = _ensure_in_firm
