"""/admin — KeyRotator state + system health snapshots. Admin role only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import RequestPrincipal, require_admin
from app.db.models.observability import AuditLog
from app.db.session import get_session
from app.llm.client import OllamaCloudLLM, get_llm

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/rotator", response_model=dict)
async def rotator_status(
    _: RequestPrincipal = Depends(require_admin),
) -> dict[str, Any]:
    """Return per-key rotator state, masked.

    If the backend is the FakeLLM (tests / minimal dev), returns a synthetic
    payload so the screen still works.
    """
    llm = get_llm()
    if not isinstance(llm, OllamaCloudLLM):
        return {"backend": llm.__class__.__name__, "keys": [], "cursor": 0}
    snap = llm.rotator.snapshot()
    return {"backend": "OllamaCloudLLM", "keys": snap.keys, "cursor": snap.cursor}


@router.get("/audit-log")
async def list_audit_log(
    _: RequestPrincipal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "firm_id": str(r.firm_id) if r.firm_id else None,
            "user_id": str(r.user_id) if r.user_id else None,
            "action": r.action,
            "target_kind": r.target_kind,
            "target_id": r.target_id,
            "meta": r.meta,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
