"""Client CRUD — firm-scoped."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import RequestPrincipal, current_principal
from app.api.errors import ApiError
from app.api.schemas.engagement import ClientIn, ClientOut
from app.db.models.engagement import Client
from app.db.session import get_session

router = APIRouter(prefix="/clients", tags=["clients"])


def _out(c: Client) -> ClientOut:
    return ClientOut(
        id=str(c.id),
        name=c.name,
        jurisdiction=c.jurisdiction,
        base_currency=c.base_currency,
        fy_end=c.fy_end,
        created_at=c.created_at,
    )


@router.get("", response_model=list[ClientOut])
async def list_clients(
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> list[ClientOut]:
    rows = (
        await session.scalars(
            select(Client).where(Client.firm_id == principal.firm_id).order_by(Client.created_at.desc())
        )
    ).all()
    return [_out(c) for c in rows]


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: ClientIn,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> ClientOut:
    c = Client(
        firm_id=principal.firm_id,
        name=payload.name,
        jurisdiction=payload.jurisdiction,
        base_currency=payload.base_currency,
        fy_end=payload.fy_end,
    )
    session.add(c)
    await session.flush()
    return _out(c)


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(
    client_id: uuid.UUID,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> ClientOut:
    c = await session.get(Client, client_id)
    if c is None or c.firm_id != principal.firm_id:
        raise ApiError(status=404, code="not_found", detail="client not found")
    return _out(c)
