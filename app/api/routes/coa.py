"""/coa — chart of accounts CRUD + template import."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import RequestPrincipal, current_principal
from app.api.errors import ApiError
from app.api.routes.engagements import ensure_in_firm
from app.api.schemas.books import CoaAccountIn, CoaAccountOut, CoaImportIn, CoaImportOut
from app.coa.templates import load_template
from app.db.models.books import AccountType, ChartOfAccount
from app.db.session import get_session

router = APIRouter(prefix="/engagements/{engagement_id}/coa", tags=["coa"])


def _out(a: ChartOfAccount) -> CoaAccountOut:
    return CoaAccountOut(
        id=str(a.id),
        code=a.code,
        name=a.name,
        type=a.type.value,
        parent_id=str(a.parent_id) if a.parent_id else None,
        currency=a.currency,
        active=a.active,
    )


@router.get("", response_model=list[CoaAccountOut])
async def list_accounts(
    engagement_id: uuid.UUID,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> list[CoaAccountOut]:
    await ensure_in_firm(engagement_id, principal, session)
    rows = (
        await session.scalars(
            select(ChartOfAccount).where(ChartOfAccount.engagement_id == engagement_id).order_by(ChartOfAccount.code)
        )
    ).all()
    return [_out(a) for a in rows]


@router.post("", response_model=CoaAccountOut, status_code=status.HTTP_201_CREATED)
async def create_account(
    engagement_id: uuid.UUID,
    payload: CoaAccountIn,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> CoaAccountOut:
    await ensure_in_firm(engagement_id, principal, session)
    parent_id = None
    if payload.parent_code:
        parent = await session.scalar(
            select(ChartOfAccount).where(
                ChartOfAccount.engagement_id == engagement_id,
                ChartOfAccount.code == payload.parent_code,
            )
        )
        if parent is None:
            raise ApiError(status=400, code="bad_request", detail=f"unknown parent_code {payload.parent_code}")
        parent_id = parent.id
    row = ChartOfAccount(
        engagement_id=engagement_id,
        code=payload.code,
        name=payload.name,
        type=AccountType(payload.type),
        parent_id=parent_id,
        currency=payload.currency,
        active=payload.active,
    )
    session.add(row)
    try:
        await session.flush()
    except Exception as exc:
        raise ApiError(status=409, code="duplicate", detail="account code already exists") from exc
    return _out(row)


@router.post("/import", response_model=CoaImportOut)
async def import_template(
    engagement_id: uuid.UUID,
    payload: CoaImportIn,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> CoaImportOut:
    await ensure_in_firm(engagement_id, principal, session)
    try:
        template = load_template(payload.template)
    except KeyError as exc:
        raise ApiError(status=400, code="bad_request", detail=str(exc)) from exc

    existing_codes = set(
        (
            await session.scalars(
                select(ChartOfAccount.code).where(ChartOfAccount.engagement_id == engagement_id)
            )
        ).all()
    )
    # Two passes so we can resolve parent_code → parent_id.
    by_code: dict[str, ChartOfAccount] = {}
    for a in template:
        if a.code in existing_codes:
            continue
        row = ChartOfAccount(
            engagement_id=engagement_id,
            code=a.code,
            name=a.name,
            type=AccountType(a.type),
        )
        session.add(row)
        by_code[a.code] = row
    await session.flush()
    for a in template:
        if a.parent_code and a.code in by_code and a.parent_code in by_code:
            by_code[a.code].parent_id = by_code[a.parent_code].id
    return CoaImportOut(imported=len(by_code))
