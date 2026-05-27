"""/audit — sampling, JE tests, workpapers, findings.

Combined into one router file because each handler is small.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import RequestPrincipal, current_principal
from app.api.errors import ApiError
from app.api.routes.engagements import ensure_in_firm
from app.api.schemas.audit import (
    FindingIn,
    FindingOut,
    JETestHitOut,
    JETestIn,
    JETestRunOut,
    SampleIn,
    SampleOut,
    WorkpaperIn,
    WorkpaperOut,
)
from app.audit.je_tests import (
    benford_hits,
    late_posting_hits,
    round_amount_hits,
    threshold_hits,
    unusual_user_hits,
    weekend_holiday_hits,
)
from app.audit.je_tests.benford import JEAmount
from app.audit.sampling import (
    SamplingItem,
    mus_sample,
    random_sample,
    stratified_sample,
)
from app.audit.workpapers.renderer import render_template
from app.db.models.audit_models import AuditFinding, JETestRun, Sample, Workpaper
from app.db.models.books import GLEntry
from app.db.session import get_session

router = APIRouter(prefix="/engagements/{engagement_id}/audit", tags=["audit"])


# ──────────────── sampling ────────────────


async def _gl_population(session: AsyncSession, engagement_id: uuid.UUID) -> list[GLEntry]:
    return (
        await session.scalars(
            select(GLEntry).where(GLEntry.engagement_id == engagement_id).order_by(GLEntry.je_date)
        )
    ).all()


@router.post("/samples", response_model=SampleOut, status_code=status.HTTP_201_CREATED)
async def draw_sample(
    engagement_id: uuid.UUID,
    payload: SampleIn,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> SampleOut:
    await ensure_in_firm(engagement_id, principal, session)
    gl = await _gl_population(session, engagement_id)
    items = [
        SamplingItem(id=str(e.id), amount=float(e.debit) - float(e.credit))
        for e in gl
    ]
    if not items:
        raise ApiError(status=400, code="empty_population", detail="no GL entries for this engagement")

    if payload.method == "random":
        result = random_sample(items, size=payload.size, seed=payload.seed)
    elif payload.method == "stratified":
        if not payload.strata_boundaries or not payload.per_stratum:
            raise ApiError(
                status=400, code="bad_request", detail="stratified sampling requires strata_boundaries + per_stratum"
            )
        result = stratified_sample(
            items,
            strata_boundaries=payload.strata_boundaries,
            per_stratum=payload.per_stratum,
            seed=payload.seed,
        )
    else:  # mus
        if not payload.performance_materiality:
            raise ApiError(
                status=400, code="bad_request", detail="mus sampling requires performance_materiality"
            )
        result = mus_sample(
            items,
            performance_materiality=payload.performance_materiality,
            seed=payload.seed,
        )

    row = Sample(
        engagement_id=engagement_id,
        method=result.method,
        population_query={"engagement_id": str(engagement_id)},
        sample_size=len(result.selected),
        sample_ids=list(result.selected),
        seed=result.seed,
        performance_materiality=payload.performance_materiality,
        drawn_at=datetime.now(tz=UTC),
    )
    session.add(row)
    await session.flush()
    return SampleOut(
        id=str(row.id),
        method=row.method,
        seed=row.seed,
        sample_size=row.sample_size,
        sample_ids=list(result.selected),
    )


# ──────────────── JE tests ────────────────


@router.post("/je-tests", response_model=JETestRunOut, status_code=status.HTTP_201_CREATED)
async def run_je_test(
    engagement_id: uuid.UUID,
    payload: JETestIn,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> JETestRunOut:
    await ensure_in_firm(engagement_id, principal, session)
    gl = await _gl_population(session, engagement_id)
    if not gl:
        raise ApiError(status=400, code="empty_population", detail="no GL entries to test")

    if payload.test_kind == "benford":
        amts = [
            JEAmount(
                id=str(e.id),
                je_number=e.je_number,
                je_date=e.je_date,
                amount=float(e.debit) - float(e.credit),
            )
            for e in gl
        ]
        hits = benford_hits(amts)
    elif payload.test_kind == "weekend_holiday":
        wrapped = [_AmountAdapter(e) for e in gl]
        hits = weekend_holiday_hits(wrapped)
    elif payload.test_kind == "round_amounts":
        wrapped = [_AmountAdapter(e) for e in gl]
        hits = round_amount_hits(wrapped, units=payload.units or 1000)
    elif payload.test_kind == "unusual_user":
        wrapped = [_AmountAdapter(e) for e in gl]
        hits = unusual_user_hits(wrapped, rare_threshold=payload.rare_threshold or 3)
    elif payload.test_kind == "late_postings":
        wrapped = [_AmountAdapter(e) for e in gl]
        hits = late_posting_hits(wrapped, max_lag_days=payload.max_lag_days or 5)
    else:  # threshold
        if payload.amount_threshold is None:
            raise ApiError(status=400, code="bad_request", detail="threshold test requires amount_threshold")
        wrapped = [_AmountAdapter(e) for e in gl]
        hits = threshold_hits(wrapped, amount_threshold=payload.amount_threshold)

    run = JETestRun(
        engagement_id=engagement_id,
        test_kind=payload.test_kind,
        filters=payload.model_dump(exclude_none=True),
        hits_count=len(hits),
        hits=hits,
        ran_at=datetime.now(tz=UTC),
        ran_by=principal.user_id if principal.user_id.int != 0 else None,
    )
    session.add(run)
    await session.flush()
    return JETestRunOut(
        id=str(run.id),
        test_kind=run.test_kind,
        hits_count=run.hits_count,
        hits=[JETestHitOut(entry_id=h["entry_id"], amount=h.get("amount", 0.0), reason=h["reason"], extra={k: v for k, v in h.items() if k not in {"entry_id", "amount", "reason"}}) for h in hits],
    )


class _AmountAdapter:
    """Adapts a GLEntry ORM row to the duck-typed objects the JE tests expect."""

    def __init__(self, gl: GLEntry) -> None:
        self._gl = gl
        self.id = str(gl.id)
        self.je_number = gl.je_number
        self.je_date = gl.je_date
        self.posting_date = gl.posting_date
        self.preparer = gl.preparer
        self.approver = gl.approver
        self.currency = gl.currency
        self.description = gl.description
        self.amount = float(gl.debit) - float(gl.credit)


# ──────────────── workpapers ────────────────


@router.post("/workpapers", response_model=WorkpaperOut, status_code=status.HTTP_201_CREATED)
async def generate_workpaper(
    engagement_id: uuid.UUID,
    payload: WorkpaperIn,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> WorkpaperOut:
    await ensure_in_firm(engagement_id, principal, session)
    rendered = render_template(
        payload.template,
        inputs={
            "title": payload.title,
            "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
            **payload.inputs,
        },
        references=payload.references,
    )
    row = Workpaper(
        engagement_id=engagement_id,
        type=payload.template,
        title=payload.title,
        body_md=rendered.body_md,
        references=rendered.references,
        prepared_by=principal.user_id if principal.user_id.int != 0 else None,
    )
    session.add(row)
    await session.flush()
    return WorkpaperOut(
        id=str(row.id),
        title=row.title,
        type=row.type,
        body_md=row.body_md,
        pdf_s3_uri=row.pdf_s3_uri,
        references=row.references,
    )


@router.get("/workpapers", response_model=list[WorkpaperOut])
async def list_workpapers(
    engagement_id: uuid.UUID,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> list[WorkpaperOut]:
    await ensure_in_firm(engagement_id, principal, session)
    rows = (
        await session.scalars(
            select(Workpaper).where(Workpaper.engagement_id == engagement_id).order_by(Workpaper.created_at.desc())
        )
    ).all()
    return [
        WorkpaperOut(
            id=str(w.id),
            title=w.title,
            type=w.type,
            body_md=w.body_md,
            pdf_s3_uri=w.pdf_s3_uri,
            references=w.references,
        )
        for w in rows
    ]


# ──────────────── findings ────────────────


@router.post("/findings", response_model=FindingOut, status_code=status.HTTP_201_CREATED)
async def create_finding(
    engagement_id: uuid.UUID,
    payload: FindingIn,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> FindingOut:
    await ensure_in_firm(engagement_id, principal, session)
    wp_id = uuid.UUID(payload.workpaper_id) if payload.workpaper_id else None
    row = AuditFinding(
        engagement_id=engagement_id,
        workpaper_id=wp_id,
        assertion=payload.assertion,
        risk_level=payload.risk_level,
        description=payload.description,
        evidence_refs=payload.evidence_refs,
    )
    session.add(row)
    await session.flush()
    return FindingOut(
        id=str(row.id),
        workpaper_id=str(row.workpaper_id) if row.workpaper_id else None,
        assertion=row.assertion,
        risk_level=row.risk_level,
        description=row.description,
        evidence_refs=row.evidence_refs,
    )


@router.get("/findings", response_model=list[FindingOut])
async def list_findings(
    engagement_id: uuid.UUID,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> list[FindingOut]:
    await ensure_in_firm(engagement_id, principal, session)
    rows = (
        await session.scalars(
            select(AuditFinding).where(AuditFinding.engagement_id == engagement_id).order_by(AuditFinding.created_at.desc())
        )
    ).all()
    return [
        FindingOut(
            id=str(r.id),
            workpaper_id=str(r.workpaper_id) if r.workpaper_id else None,
            assertion=r.assertion,
            risk_level=r.risk_level,
            description=r.description,
            evidence_refs=r.evidence_refs,
        )
        for r in rows
    ]
