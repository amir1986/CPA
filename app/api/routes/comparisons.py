"""USGAAP <> IFRS comparison runs.

A top-level (non-engagement) endpoint group that:

- Accepts a multipart upload of one or more files (PDF / DOCX / XLSX / CSV).
- Persists them under a hidden per-user "comparisons" engagement so the
  existing files + workpapers code paths can be reused unchanged.
- Kicks the orchestrator (`asyncio.create_task`) which extracts text,
  classifies framework, identifies issues, and runs side-by-side standards
  retrieval.
- Streams progress over SSE.
- Renders a multi-issue memo via the existing `comparison_memo` workpaper
  template — once per issue, concatenated.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import mimetypes
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, UploadFile, status
from fastapi import File as FileParam
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import RequestPrincipal
from app.api.auth import current_principal_permissive as current_principal
from app.api.errors import ApiError
from app.audit.workpapers.renderer import render_pdf_bytes
from app.db.models.comparison_models import (
    ComparisonIssue,
    ComparisonRun,
    ComparisonStatus,
    Framework,
)
from app.db.models.files import File, FileKind, ParsedStatus
from app.db.session import get_session, get_sessionmaker
from app.services.comparison_orchestrator import (
    SUPPORTED_MIMES,
    run_orchestrator,
)
from app.services.comparisons_engagement import get_or_create_hidden_engagement
from app.storage.paths import raw_key, s3_uri
from app.storage.s3 import get_object_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/comparison", tags=["comparison"])

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB per file; smaller than engagement files
MAX_FILES_PER_RUN = 10

# Keep strong refs to orchestrator tasks so the GC can't reap them mid-flight.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


# ─────────────── schemas ───────────────


class IssueOut(BaseModel):
    id: str
    seq: int
    topic: str
    current_summary: str
    current_user_cites: list[dict]
    gaap_summary: str | None
    gaap_citations: list[dict]
    ifrs_summary: str | None
    ifrs_citations: list[dict]
    differences: str | None
    conversion_impact: str | None
    gaap_verification: str | None = None
    ifrs_verification: str | None = None


class RunOut(BaseModel):
    id: str
    status: str
    detected_framework: str | None
    override_framework: str | None
    confidence: float | None
    rationale: str | None
    error: str | None
    file_ids: list[str]
    file_names: list[str]
    issues: list[IssueOut]
    created_at: datetime


class RunSummary(BaseModel):
    id: str
    status: str
    detected_framework: str | None
    override_framework: str | None
    issue_count: int
    file_names: list[str]
    created_at: datetime


class FrameworkPatch(BaseModel):
    framework: str   # "US" or "IFRS"


class ExportIn(BaseModel):
    format: str = "md"   # "md" or "pdf"


# ─────────────── helpers ───────────────


async def _load_run(
    run_id: uuid.UUID,
    principal: RequestPrincipal,
    session: AsyncSession,
) -> ComparisonRun:
    run = await session.get(ComparisonRun, run_id)
    if run is None or run.user_id != principal.user_id:
        raise ApiError(status=404, code="not_found", detail="run not found")
    return run


async def _issues_for(run_id: uuid.UUID, session: AsyncSession) -> list[ComparisonIssue]:
    return list(
        (
            await session.scalars(
                select(ComparisonIssue)
                .where(ComparisonIssue.run_id == run_id)
                .order_by(ComparisonIssue.seq)
            )
        ).all()
    )


def _issue_out(i: ComparisonIssue) -> IssueOut:
    return IssueOut(
        id=str(i.id),
        seq=i.seq,
        topic=i.topic,
        current_summary=i.current_summary,
        current_user_cites=list(i.current_user_cites or []),
        gaap_summary=i.gaap_summary,
        gaap_citations=list(i.gaap_citations or []),
        ifrs_summary=i.ifrs_summary,
        ifrs_citations=list(i.ifrs_citations or []),
        differences=i.differences,
        conversion_impact=i.conversion_impact,
        gaap_verification=i.gaap_verification,
        ifrs_verification=i.ifrs_verification,
    )


def _kind_supported(file: UploadFile) -> bool:
    if (file.content_type or "").lower() in SUPPORTED_MIMES:
        return True
    name = (file.filename or "").lower()
    return name.endswith((".pdf", ".docx", ".xlsx", ".csv"))


# ─────────────── routes ───────────────


@router.post("/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def create_run(
    files: list[UploadFile] = FileParam(...),
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> RunOut:
    if not files:
        raise ApiError(status=400, code="bad_request", detail="at least one file required")
    if len(files) > MAX_FILES_PER_RUN:
        raise ApiError(status=400, code="bad_request", detail=f"max {MAX_FILES_PER_RUN} files per run")
    for f in files:
        if not _kind_supported(f):
            raise ApiError(
                status=400,
                code="unsupported_file",
                detail=f"unsupported file type: {f.filename} (mime={f.content_type})",
            )

    eng = await get_or_create_hidden_engagement(
        user_id=principal.user_id, firm_id=principal.firm_id, session=session
    )

    store = get_object_store()
    file_rows: list[File] = []
    file_ids: list[str] = []
    file_names: list[str] = []
    for f in files:
        body = await f.read()
        if not body:
            raise ApiError(status=400, code="empty_file", detail=f"empty file: {f.filename}")
        if len(body) > MAX_FILE_SIZE:
            raise ApiError(status=413, code="too_large", detail=f"{f.filename} exceeds 50 MB")
        file_id = uuid.uuid4()
        mime = f.content_type or mimetypes.guess_type(f.filename or "")[0]
        key = raw_key(engagement_id=eng.id, file_id=file_id, filename=f.filename or "upload")
        await store.put(key, body, content_type=mime)
        row = File(
            id=file_id,
            engagement_id=eng.id,
            kind=_guess_file_kind(f.filename or ""),
            original_name=f.filename or "upload",
            s3_uri=s3_uri(key),
            sha256=hashlib.sha256(body).hexdigest(),
            mime=mime,
            size=len(body),
            parsed_status=ParsedStatus.queued,
            uploaded_by=principal.user_id,
        )
        session.add(row)
        file_rows.append(row)
        file_ids.append(str(file_id))
        file_names.append(row.original_name)
    await session.flush()

    run = ComparisonRun(
        engagement_id=eng.id,
        user_id=principal.user_id,
        status=ComparisonStatus.parsing,
        file_ids=file_ids,
    )
    session.add(run)
    await session.commit()

    # Fire-and-forget orchestrator. The run's status field is the source of
    # truth that the SSE stream and GET endpoint poll. Stash the task on the
    # module so the garbage collector can't reap it mid-run.
    task = asyncio.create_task(run_orchestrator(run.id))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)

    return RunOut(
        id=str(run.id),
        status=run.status.value,
        detected_framework=None,
        override_framework=None,
        confidence=None,
        rationale=None,
        error=None,
        file_ids=file_ids,
        file_names=file_names,
        issues=[],
        created_at=run.created_at,
    )


def _guess_file_kind(name: str) -> FileKind:
    n = name.lower()
    if n.endswith((".docx",)):
        return FileKind.policy
    if n.endswith(".pdf"):
        return FileKind.contract
    if n.endswith(".xlsx"):
        return FileKind.financial_statements
    if n.endswith(".csv"):
        return FileKind.gl
    return FileKind.other


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> list[RunSummary]:
    rows = (
        await session.scalars(
            select(ComparisonRun)
            .where(ComparisonRun.user_id == principal.user_id)
            .order_by(ComparisonRun.created_at.desc())
        )
    ).all()
    out: list[RunSummary] = []
    for r in rows:
        issues = await _issues_for(r.id, session)
        # Resolve file names for the summary card.
        names: list[str] = []
        for fid in r.file_ids:
            f = await session.get(File, uuid.UUID(fid))
            if f is not None:
                names.append(f.original_name)
        out.append(
            RunSummary(
                id=str(r.id),
                status=r.status.value,
                detected_framework=r.detected_framework.value if r.detected_framework else None,
                override_framework=r.override_framework.value if r.override_framework else None,
                issue_count=len(issues),
                file_names=names,
                created_at=r.created_at,
            )
        )
    return out


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(
    run_id: uuid.UUID,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> RunOut:
    run = await _load_run(run_id, principal, session)
    issues = await _issues_for(run.id, session)
    names: list[str] = []
    for fid in run.file_ids:
        f = await session.get(File, uuid.UUID(fid))
        if f is not None:
            names.append(f.original_name)
    return RunOut(
        id=str(run.id),
        status=run.status.value,
        detected_framework=run.detected_framework.value if run.detected_framework else None,
        override_framework=run.override_framework.value if run.override_framework else None,
        confidence=run.confidence,
        rationale=run.rationale,
        error=run.error,
        file_ids=run.file_ids,
        file_names=names,
        issues=[_issue_out(i) for i in issues],
        created_at=run.created_at,
    )


@router.post("/runs/{run_id}/framework", response_model=RunOut)
async def set_framework_override(
    run_id: uuid.UUID,
    payload: FrameworkPatch,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> RunOut:
    run = await _load_run(run_id, principal, session)
    if payload.framework not in ("US", "IFRS"):
        raise ApiError(status=400, code="bad_request", detail="framework must be 'US' or 'IFRS'")
    run.override_framework = Framework(payload.framework)
    await session.commit()
    return await get_run(run_id, principal, session)


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: uuid.UUID,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    # Authorize once before opening the stream.
    await _load_run(run_id, principal, session)

    async def gen() -> AsyncIterator[bytes]:
        # Preamble: 2 KB of SSE comment lines so Cloudflare / Render's
        # edge layer flushes immediately instead of buffering the response
        # until enough bytes accumulate. Without this, the browser sees
        # zero events for ~30 s even though the api is emitting them.
        yield (b": " + b"x" * 2048 + b"\n\n")

        factory = get_sessionmaker()
        last_status: str | None = None
        last_heartbeat = 0
        # ≤ 5 minutes; polls every 1 s, heartbeats every 5 s so the
        # connection stays unbuffered and idle proxies don't drop it.
        for tick in range(300):
            async with factory() as s2:
                row = await s2.get(ComparisonRun, run_id)
                if row is None:
                    yield b"event: error\ndata: {\"detail\":\"vanished\"}\n\n"
                    return
                cur = row.status.value
                if cur != last_status:
                    payload = {
                        "status": cur,
                        "detected_framework": row.detected_framework.value if row.detected_framework else None,
                        "confidence": row.confidence,
                        "error": row.error,
                    }
                    yield f"event: status\ndata: {json.dumps(payload)}\n\n".encode()
                    last_status = cur
                if cur in {"done", "failed"}:
                    yield b"event: done\ndata: {}\n\n"
                    return
            # Heartbeat keeps the connection alive and forces a flush even
            # when no status change happened.
            if tick - last_heartbeat >= 5:
                yield b": heartbeat\n\n"
                last_heartbeat = tick
            await asyncio.sleep(1)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            # `no-transform` keeps Cloudflare from gzip-buffering the stream;
            # `identity` content-encoding belt-and-suspenders for the same
            # concern. `X-Accel-Buffering: no` covers nginx.
            "Cache-Control": "no-cache, no-transform",
            "Content-Encoding": "identity",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/export")
async def export_memo(
    run_id: uuid.UUID,
    payload: ExportIn,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    run = await _load_run(run_id, principal, session)
    if run.status != ComparisonStatus.done:
        raise ApiError(status=400, code="not_ready", detail=f"run not done yet (status={run.status.value})")
    issues = await _issues_for(run.id, session)
    if not issues:
        raise ApiError(status=400, code="empty", detail="run produced no issues to export")

    generated_at = datetime.now(tz=UTC).isoformat(timespec="seconds")
    framework = (run.override_framework or run.detected_framework or Framework.US).value
    sections: list[str] = []
    sections.append(
        "> **DRAFT — REQUIRES PARTNER REVIEW**\n\n"
        f"# USGAAP <> IFRS comparison\n\n"
        f"**Detected framework:** {framework}\n"
        f"**Generated:** {generated_at}\n"
    )
    if run.confidence is not None:
        sections.append(f"**Detection confidence:** {run.confidence:.2f}\n")
    if run.rationale:
        sections.append(f"**Rationale:** {run.rationale}\n")
    for i in issues:
        sections.append(_format_issue_section(i))
    full = "\n\n---\n\n".join(sections)

    safe_name = f"usgaap-ifrs-comparison-{run.id}"
    if payload.format == "pdf":
        # render_pdf_bytes is CPU-bound (fpdf2 walks every line, shapes
        # glyphs, embeds a Unicode TTF). Running it inline blocks the
        # event loop for the duration — long enough on a multi-issue
        # Hebrew memo that Render's edge times out the request with 502.
        # Off-thread it + cap with asyncio.wait_for so a pathological
        # render can't pin the worker forever.
        try:
            # No content cap — the full memo (every cite quote, every issue)
            # goes into the PDF. Timeout is generous (5 minutes) so even a
            # large multi-issue Hebrew export has room.
            pdf_bytes = await asyncio.wait_for(
                asyncio.to_thread(render_pdf_bytes, full),
                timeout=300.0,
            )
        except RuntimeError as exc:
            raise ApiError(status=503, code="pdf_unavailable", detail=str(exc)) from exc
        except TimeoutError as exc:
            raise ApiError(
                status=504,
                code="pdf_timeout",
                detail="PDF rendering took longer than 5 minutes — try the markdown export instead",
            ) from exc
        except Exception as exc:
            logger.exception("pdf render crashed for run %s", run_id)
            raise ApiError(
                status=500,
                code="pdf_render_failed",
                detail=f"PDF render failed: {exc}",
            ) from exc
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.pdf"'},
        )
    return StreamingResponse(
        io.BytesIO(full.encode("utf-8")),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.md"'},
    )


def _format_issue_section(i: ComparisonIssue) -> str:
    """Render one issue as a self-contained markdown section with the
    EXACT source paragraphs (verbatim quotes) inline next to each side's
    implementation summary, plus the verifier agent's correctness report.

    Layout:
      ## #{seq} {topic}
      ### Current treatment (from your document)
      <current_summary>
      #### Source paragraphs from your document
      > [anchor] verbatim text
      ### US GAAP treatment
      <gaap_summary>
      #### Source paragraphs from US GAAP standards
      > **standard ¶para** — url
      > "verbatim quote"
      #### Verifier agent
      <gaap_verification>
      ### IFRS treatment
      ... (same shape)
      ### Key differences
      ### Conversion impact
    """
    parts: list[str] = []
    parts.append(f"## #{i.seq} {i.topic}\n")

    # --- Current treatment from the user's document ---
    parts.append("### Current treatment (from your document)\n")
    parts.append((i.current_summary or "_(no current treatment summary)_") + "\n")
    if i.current_user_cites:
        parts.append("#### Source paragraphs from your document\n")
        for c in i.current_user_cites:
            anchor = c.get("anchor") or c.get("ref") or "?"
            quote = (c.get("quote") or "").strip()
            parts.append(f"> **{anchor}**")
            if quote:
                parts.append(f"> {quote}")
            parts.append("")  # blank line between cites

    # --- US GAAP side ---
    parts.append("### US GAAP treatment\n")
    parts.append((i.gaap_summary or "_(no US GAAP standards retrieved)_") + "\n")
    parts.append("#### Source paragraphs from US GAAP standards\n")
    parts.append(_format_inline_cites(i.gaap_citations))
    if i.gaap_verification:
        parts.append("#### Verifier agent (US GAAP)\n")
        parts.append(i.gaap_verification + "\n")

    # --- IFRS side ---
    parts.append("### IFRS treatment\n")
    parts.append((i.ifrs_summary or "_(no IFRS standards retrieved)_") + "\n")
    parts.append("#### Source paragraphs from IFRS standards\n")
    parts.append(_format_inline_cites(i.ifrs_citations))
    if i.ifrs_verification:
        parts.append("#### Verifier agent (IFRS)\n")
        parts.append(i.ifrs_verification + "\n")

    # --- Differences + conversion impact ---
    parts.append("### Key differences\n")
    parts.append((i.differences or "_See side-by-side summaries above._") + "\n")
    if i.conversion_impact:
        parts.append("### Conversion impact\n")
        parts.append(i.conversion_impact + "\n")

    return "\n".join(parts)


def _format_inline_cites(cites: list[dict]) -> str:
    """Each cited paragraph is rendered as a labelled blockquote so it
    visually sits next to the summary it backs. Verbatim quotes are
    preserved in full — no truncation."""
    if not cites:
        return "_(none retrieved — see verifier note below)_\n"
    out: list[str] = []
    for c in cites:
        std = c.get("standard") or "(no standard)"
        para = c.get("paragraph")
        url = c.get("url") or ""
        quote = (c.get("quote") or "").strip()
        header = f"> **{std}**"
        if para:
            header += f" ¶{para}"
        out.append(header)
        if quote:
            out.append(f"> _\"{quote}\"_")
        if url:
            out.append(f"> source: {url}")
        out.append("")
    return "\n".join(out)


def _format_citations(cites: list[dict]) -> str:
    if not cites:
        return "_(none)_"
    lines: list[str] = []
    for c in cites:
        std = c.get("standard") or "(no standard)"
        para = c.get("paragraph")
        url = c.get("url") or ""
        quote = (c.get("quote") or "").strip()
        head = f"- **{std}**"
        if para:
            head += f" ¶{para}"
        if url:
            head += f" — {url}"
        if quote:
            head += f"\n  > {quote}"
        lines.append(head)
    return "\n".join(lines)


def _format_user_cites(cites: list[dict]) -> str:
    if not cites:
        return ""
    lines: list[str] = []
    for c in cites:
        anchor = c.get("anchor") or c.get("ref") or "?"
        quote = (c.get("quote") or "").strip()
        head = f"- _{anchor}_"
        if quote:
            head += f": {quote}"
        lines.append(head)
    return "\n".join(lines)
