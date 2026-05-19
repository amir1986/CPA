"""/gl and /trial-balance read-only endpoints."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import RequestPrincipal, current_principal
from app.api.routes.engagements import ensure_in_firm
from app.api.schemas.books import GLEntryOut, GLListOut, TrialBalanceOut
from app.db.models.books import GLEntry, TrialBalance
from app.db.session import get_session

router = APIRouter(prefix="/engagements/{engagement_id}", tags=["books"])


def _gl_out(e: GLEntry) -> GLEntryOut:
    return GLEntryOut(
        id=str(e.id),
        je_number=e.je_number,
        je_date=e.je_date,
        posting_date=e.posting_date,
        account_id=str(e.account_id) if e.account_id else None,
        debit=float(e.debit),
        credit=float(e.credit),
        currency=e.currency,
        description=e.description,
        preparer=e.preparer,
        approver=e.approver,
    )


@router.get("/gl", response_model=GLListOut)
async def list_gl(
    engagement_id: uuid.UUID,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    account_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> GLListOut:
    await ensure_in_firm(engagement_id, principal, session)
    stmt = select(GLEntry).where(GLEntry.engagement_id == engagement_id)
    if date_from is not None:
        stmt = stmt.where(GLEntry.je_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(GLEntry.je_date <= date_to)
    if account_id is not None:
        stmt = stmt.where(GLEntry.account_id == account_id)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await session.scalars(stmt.order_by(GLEntry.je_date.desc()).limit(limit).offset(offset))
    ).all()
    return GLListOut(items=[_gl_out(r) for r in rows], total=int(total or 0))


@router.get("/trial-balance", response_model=list[TrialBalanceOut])
async def list_trial_balance(
    engagement_id: uuid.UUID,
    period_end: date,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> list[TrialBalanceOut]:
    await ensure_in_firm(engagement_id, principal, session)
    rows = (
        await session.scalars(
            select(TrialBalance)
            .where(TrialBalance.engagement_id == engagement_id, TrialBalance.period_end == period_end)
            .order_by(TrialBalance.account_code)
        )
    ).all()
    return [
        TrialBalanceOut(
            id=str(r.id),
            period_end=r.period_end,
            account_id=str(r.account_id) if r.account_id else None,
            account_code=r.account_code,
            account_name=r.account_name,
            opening=float(r.opening),
            debit_total=float(r.debit_total),
            credit_total=float(r.credit_total),
            closing=float(r.closing),
        )
        for r in rows
    ]
