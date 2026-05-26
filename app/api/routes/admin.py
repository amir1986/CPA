"""/admin — KeyRotator state + system health snapshots. Admin role only."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, Header
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import RequestPrincipal, require_admin
from app.api.errors import ApiError
from app.config import get_settings
from app.db.models.observability import AuditLog
from app.db.models.standards_ingest import StandardsIngestRun, StandardsIngestStatus
from app.db.session import get_session, get_sessionmaker
from app.ingest_standards.pipeline import ingest_source
from app.ingest_standards.registry import load_sources
from app.llm.client import OllamaCloudLLM, get_llm

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

# Keep refs to in-flight ingest tasks so the GC doesn't reap them and so
# we can detect "already running" before kicking another (free-tier won't
# survive multiple parallel HTTP-heavy crawls).
_INGEST_TASKS: set[asyncio.Task[None]] = set()


@router.post("/migrate", include_in_schema=False)
async def trigger_migrate(
    x_admin_key: str = Header(default="", alias="X-Admin-Key"),
) -> dict[str, Any]:
    """Run `alembic upgrade head` from within the running container.

    Workaround for the case where the startCommand's alembic step failed
    silently and uvicorn started against an empty schema. Admin-key-gated.
    """
    settings = get_settings()
    if x_admin_key != settings.admin_api_key.get_secret_value():
        raise ApiError(status=403, code="forbidden", detail="invalid admin key")

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
    }


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


# ──────────────── standards corpus refresh ────────────────


class IngestRunOut(BaseModel):
    id: str
    source_id: str
    status: str
    chunks_count: int | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class RefreshOut(BaseModel):
    triggered: list[str]
    skipped: list[str]   # already running for these source_ids


def _ingest_run_out(r: StandardsIngestRun) -> IngestRunOut:
    return IngestRunOut(
        id=str(r.id),
        source_id=r.source_id,
        status=r.status.value,
        chunks_count=r.chunks_count,
        error=r.error,
        started_at=r.started_at,
        finished_at=r.finished_at,
    )


async def _run_one_ingest(source_id: str, run_id: uuid.UUID) -> None:
    """Background task: fetch + chunk + embed one source, then close out
    the StandardsIngestRun row. Opens its own session (the request's is
    closed by the time we run).
    """
    from app.ingest_standards.fetcher import http_fetch

    factory = get_sessionmaker()
    started = datetime.now(tz=UTC)
    try:
        sources = [s for s in load_sources() if s.id == source_id]
        if not sources:
            raise RuntimeError(f"unknown source_id: {source_id}")
        source = sources[0]
        n = await ingest_source(source, fetcher=http_fetch, full_resync=True)
        async with factory() as session:
            row = await session.get(StandardsIngestRun, run_id)
            if row is not None:
                row.status = StandardsIngestStatus.done
                row.chunks_count = int(n)
                row.finished_at = datetime.now(tz=UTC)
                await session.commit()
        logger.info("standards ingest done: source=%s chunks=%d", source_id, n)
    except Exception as exc:
        logger.exception("standards ingest failed: %s", source_id)
        async with factory() as session:
            row = await session.get(StandardsIngestRun, run_id)
            if row is not None:
                row.status = StandardsIngestStatus.failed
                row.error = f"{type(exc).__name__}: {exc}"[:1000]
                row.finished_at = datetime.now(tz=UTC)
                await session.commit()
    finally:
        # Idle for at least the started timestamp interval so any
        # observer can see we actually attempted work.
        _ = started


class RefreshIn(BaseModel):
    """Optional body for /standards/refresh.

    Accepting an object (with an optional ``source_ids`` field) rather than
    a bare list lets the StandardsRefresh client POST ``{}`` for a full
    refresh — sending a bare-list body from JS is awkward and the previous
    ``source_ids: list[str] | None = None`` signature 422'd on the empty
    object.
    """

    source_ids: list[str] | None = None


@router.post("/standards/refresh", response_model=RefreshOut)
async def refresh_standards(
    body: RefreshIn = Body(default_factory=RefreshIn),
    principal: RequestPrincipal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RefreshOut:
    """Trigger a (re-)ingest of one or more sources from config/sources.yaml.

    With no body (or `{}`) the entire registry is refreshed. Each source
    runs in a fire-and-forget background task; the response returns
    immediately with the list of source_ids that were enqueued. Sources
    already in a 'running' state are skipped so a double-click doesn't
    pile up jobs.
    """
    all_sources = load_sources()
    target_ids = body.source_ids or [s.id for s in all_sources]
    triggered: list[str] = []
    skipped: list[str] = []

    for sid in target_ids:
        # Skip if a run is already in flight for this source.
        in_flight = (
            await session.scalars(
                select(StandardsIngestRun)
                .where(StandardsIngestRun.source_id == sid)
                .where(StandardsIngestRun.status == StandardsIngestStatus.running)
            )
        ).first()
        if in_flight is not None:
            skipped.append(sid)
            continue

        row = StandardsIngestRun(
            source_id=sid,
            status=StandardsIngestStatus.running,
            started_at=datetime.now(tz=UTC),
            triggered_by=principal.user_id if principal.user_id.int != 0 else None,
        )
        session.add(row)
        await session.flush()

        task = asyncio.create_task(_run_one_ingest(sid, row.id))
        _INGEST_TASKS.add(task)
        task.add_done_callback(_INGEST_TASKS.discard)
        triggered.append(sid)

    await session.commit()
    return RefreshOut(triggered=triggered, skipped=skipped)


@router.get("/standards/runs", response_model=list[IngestRunOut])
async def list_standards_runs(
    _: RequestPrincipal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
) -> list[IngestRunOut]:
    """Most-recent ingest runs across all sources."""
    rows = (
        await session.scalars(
            select(StandardsIngestRun)
            .order_by(StandardsIngestRun.started_at.desc())
            .limit(limit)
        )
    ).all()
    return [_ingest_run_out(r) for r in rows]
