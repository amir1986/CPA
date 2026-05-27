"""/analyze — ratios + Benford. Computed from the persisted TB and GL."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyze.anomalies import benford_first_digit
from app.analyze.ratios import TBSnapshot, compute_all
from app.api.auth import RequestPrincipal, current_principal
from app.api.errors import ApiError
from app.api.routes.engagements import ensure_in_firm
from app.api.schemas.audit import BenfordRunOut, RatioOut, RatioRunOut
from app.db.models.books import ChartOfAccount, GLEntry, TrialBalance
from app.db.session import get_session

router = APIRouter(prefix="/engagements/{engagement_id}/analyze", tags=["analyze"])


async def _snapshot(session: AsyncSession, engagement_id: uuid.UUID, period_end: date) -> TBSnapshot:
    rows = (
        await session.scalars(
            select(TrialBalance).where(
                TrialBalance.engagement_id == engagement_id,
                TrialBalance.period_end == period_end,
            )
        )
    ).all()
    if not rows:
        raise ApiError(status=404, code="not_found", detail="no trial balance for that period")
    coa = (
        await session.scalars(
            select(ChartOfAccount).where(ChartOfAccount.engagement_id == engagement_id)
        )
    ).all()
    type_by_id = {a.id: a.type.value for a in coa}

    by_code: dict[str, float] = {}
    by_type: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        amt = float(r.closing)
        if r.account_code:
            by_code[r.account_code] = amt
        atype = type_by_id.get(r.account_id) if r.account_id else None
        if atype is None:
            continue
        by_type[atype].append(amt)
    return TBSnapshot(period_end=period_end, by_code=by_code, by_type=dict(by_type))


@router.get("/ratios", response_model=RatioRunOut)
async def ratios(
    engagement_id: uuid.UUID,
    period_end: date,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> RatioRunOut:
    await ensure_in_firm(engagement_id, principal, session)
    snap = await _snapshot(session, engagement_id, period_end)
    results = compute_all(snap)
    return RatioRunOut(
        period_end=period_end,
        ratios=[
            RatioOut(
                name=r.name,
                period_end=r.period_end,
                value=r.value,
                numerator=r.numerator,
                denominator=r.denominator,
            )
            for r in results
        ],
    )


@router.get("/benford", response_model=BenfordRunOut)
async def benford(
    engagement_id: uuid.UUID,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> BenfordRunOut:
    await ensure_in_firm(engagement_id, principal, session)
    result = await session.execute(
        select(GLEntry.debit, GLEntry.credit).where(GLEntry.engagement_id == engagement_id)
    )
    amounts = [float(d or 0) - float(c or 0) for d, c in result.all()]
    summary = benford_first_digit(amounts)
    return BenfordRunOut(
        observed=summary.observed,
        observed_pct=summary.observed_pct,
        expected_pct=summary.expected_pct,
        chi_square=summary.chi_square,
        n=summary.n,
        suspect=summary.suspect,
    )
