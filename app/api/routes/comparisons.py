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

# Translation helpers live in `app/services/comparison_translation.py` so
# the orchestrator can kick HE pre-translation without an import cycle
# through this routes module. The "private" names are re-exported here so
# existing tests (`tests/unit/test_comparison_translate.py`) keep
# targeting `routes._translate_to_hebrew` etc. unchanged.
from app.services.comparison_translation import (
    PROSE_KEYS as _PROSE_KEYS_FROM_SVC,
)
from app.services.comparison_translation import (
    _flatten_for_translation,
    _translate_batches_parallel,
    _translate_to_hebrew,
    kick_pretranslation,
    localize_boilerplate,
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
    # Locale for section headings + labels in the memo. Defaults to Hebrew
    # (the app's default locale); only an explicit "en" produces an English
    # memo. Verbatim quotes are NEVER translated — they're preserved in
    # their source language (Hebrew XLSX rows stay Hebrew, English standards
    # stay English).
    locale: str = "he"


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
    # Auto-retry Hebrew pre-translation for a done run whose cache is
    # missing or incomplete. The original `kick_pretranslation` at
    # orchestrator-completion time is best-effort and can fail silently
    # (Ollama Cloud transient, worker restart, slow key). Without this
    # retry path, a single failure leaves the cache empty forever and
    # every export degrades to English body prose. Re-kicking here is
    # idempotent: `pretranslate_run_to_hebrew` short-circuits when the
    # cache already covers every prose key, and only re-sends MISSING
    # keys to the LLM otherwise.
    if run.status == ComparisonStatus.done:
        flat = _flatten_for_translation(
            run.rationale, list(issues),
        )
        cache = run.translations_he or {}
        if flat and not all(k in cache for k in flat):
            kick_pretranslation(run.id)
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
    try:
        return await _export_memo_impl(run_id, payload, principal, session)
    except ApiError:
        # Application-level errors (400 not_ready, 400 empty, 404 not_found,
        # 504 pdf_timeout) carry an actionable detail field — let FastAPI's
        # ApiError handler serialize them to problem+json so the UI can
        # show the message.
        raise
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError, GeneratorExit):
        # Process / task control signals — propagate so uvicorn shutdown
        # and ASGI cancellation still work.
        raise
    except BaseException as exc:
        # Belt-and-suspenders outer catch. Every inner layer (renderer,
        # translation, per-issue formatting) already degrades on
        # BaseException, but if a future change reintroduces a 500 vector
        # we still want the user to see something better than the opaque
        # "הייצוא נכשל (500)" pill. For PDF requests we ship a stub PDF
        # (the renderer's stated policy: always-downloadable). For MD
        # requests we surface a JSON detail the UI can show inline.
        logger.exception("export_memo top-level crash for run %s", run_id)
        if payload.format == "pdf":
            from app.audit.workpapers.renderer import _stub_pdf

            return StreamingResponse(
                io.BytesIO(_stub_pdf(f"Export crashed: {exc!r}")),
                media_type="application/pdf",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="usgaap-ifrs-comparison-{run_id}.pdf"'
                    )
                },
            )
        raise ApiError(
            status=500,
            code="export_crashed",
            detail=f"Export crashed before the memo could be rendered: {exc!r}",
        ) from exc


async def _export_memo_impl(
    run_id: uuid.UUID,
    payload: ExportIn,
    principal: RequestPrincipal,
    session: AsyncSession,
) -> StreamingResponse:
    run = await _load_run(run_id, principal, session)
    if run.status != ComparisonStatus.done:
        raise ApiError(status=400, code="not_ready", detail=f"run not done yet (status={run.status.value})")
    issues = await _issues_for(run.id, session)
    if not issues:
        raise ApiError(status=400, code="empty", detail="run produced no issues to export")

    generated_at = datetime.now(tz=UTC).isoformat(timespec="seconds")
    framework = (run.override_framework or run.detected_framework or Framework.US).value
    # Hebrew is the default; only an explicit "en" opts out.
    locale = "en" if payload.locale == "en" else "he"
    strings = _MEMO_STRINGS[locale]

    # For Hebrew exports, fill the per-issue prose dict from
    # `run.translations_he` — populated by a background task right after
    # the orchestrator marks the run `done` (see
    # `comparison_translation.pretranslate_run_to_hebrew`). The cache
    # path is instant and serves a 100% Hebrew memo.
    #
    # If the user exported before the background task finished, or it
    # failed, fall back to synchronous translation with a tight wall-
    # clock cap so the response doesn't 500 on Render's ~30 s edge idle
    # timeout. The cap fallback still ships a memo — section headings
    # come from `_MEMO_STRINGS["he"]` regardless, only the LLM prose
    # degrades to English.
    PROSE_KEYS = _PROSE_KEYS_FROM_SVC
    rationale_text = run.rationale or ""
    per_issue_prose: list[dict[str, str | None]] = []
    translated: dict[str, str] = {}
    if locale == "he":
        flat = _flatten_for_translation(rationale_text, issues)
        cache: dict[str, str] = dict(run.translations_he or {})
        # `cache` covers every key we need => skip the LLM entirely.
        if flat and all(k in cache for k in flat):
            translated = {**flat, **cache}
            logger.info(
                "Hebrew memo export: served %d prose fields from cache "
                "(run %s)",
                len(flat), run.id,
            )
        elif not flat:
            translated = {}
        else:
            # Partial or empty cache. Translate the rest on the request
            # path under a 22 s wall-clock cap — anything beyond that
            # risks the Render edge closing the idle upstream and
            # returning a text/plain 500 that bypasses every exception
            # handler. Pre-seed `translated` with whatever the cache
            # does have so we don't re-translate it.
            #
            # Also fire off pre-translation in the background. The sync
            # call below might degrade keys to English under the 22s
            # cap; the background task uses the longer 90s per-batch
            # budget and persists whatever it manages to translate, so
            # the user's NEXT export hits a fuller cache. This is the
            # auto-retry loop that gets a slow run's Hebrew memo to 100%
            # over a couple of export attempts instead of staying half-
            # English forever.
            kick_pretranslation(run.id)
            missing = {k: v for k, v in flat.items() if k not in cache}
            try:
                fresh = await asyncio.wait_for(
                    _translate_batches_parallel(missing, batch_size=2),
                    timeout=22.0,
                )
            except (KeyboardInterrupt, SystemExit, asyncio.CancelledError, GeneratorExit):
                raise
            except TimeoutError as exc:
                logger.warning(
                    "Hebrew memo translation exceeded 22s wall-clock cap "
                    "(run %s, %d uncached keys, %d cached): %r",
                    run.id, len(missing), len(cache), exc,
                )
                fresh = dict(missing)
            except BaseException as exc:
                # Don't 500 because translation glitched — ship the memo
                # with English prose for the uncached portion. Catches
                # BaseException because cryptography's pyo3 bindings can
                # raise a non-Exception panic during the LLM client's TLS
                # handshake on Render's slim install.
                logger.warning(
                    "Hebrew memo translation failed (run %s); "
                    "exporting English for %d uncached keys: %r",
                    run.id, len(missing), exc,
                )
                fresh = dict(missing)
            translated = {**flat, **cache, **fresh}
        rationale_text = translated.get("_run.rationale", rationale_text)
        # Boilerplate localization runs last so any LLM-translated value
        # is kept verbatim (its English substrings no longer match), but
        # canned phrases the LLM left in English — typically the
        # "[synthesized from model knowledge — no standards retrieved]"
        # marker and the verifier no-corpus sentence — get flipped to
        # Hebrew deterministically. This is the only thing standing
        # between a degraded translation and a half-English Hebrew PDF.
        rationale_text = localize_boilerplate(rationale_text, locale) or rationale_text

    for i in issues:
        prose: dict[str, str | None] = {
            k: (translated.get(f"{i.id}.{k}", getattr(i, k)) if locale == "he"
                else getattr(i, k))
            for k in PROSE_KEYS
        }
        if locale == "he":
            prose = {k: localize_boilerplate(v, locale) for k, v in prose.items()}
        per_issue_prose.append(prose)

    # Assemble the memo body. Each section is wrapped individually so one
    # bad issue (e.g. citation row corrupted to a non-dict shape) can't
    # nuke the whole export with an unhandled AttributeError that bubbles
    # up to FastAPI's 500 handler.
    sections: list[str] = []
    sections.append(
        f"> {strings['draft_banner']}\n\n"
        f"# {strings['title']}\n\n"
        f"**{strings['detected_framework']}:** {framework}\n"
        f"**{strings['generated']}:** {generated_at}\n"
    )
    if run.confidence is not None:
        sections.append(f"**{strings['confidence']}:** {run.confidence:.2f}\n")
    if rationale_text:
        sections.append(f"**{strings['rationale']}:** {rationale_text}\n")
    for issue_idx, i in enumerate(issues):
        try:
            sections.append(_format_issue_section(i, per_issue_prose[issue_idx], locale))
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError, GeneratorExit):
            raise
        except BaseException as exc:
            logger.warning(
                "issue #%d (%s) formatting raised %r — substituting placeholder",
                getattr(i, "seq", issue_idx), getattr(i, "id", "?"), exc,
            )
            sections.append(
                f"## #{getattr(i, 'seq', issue_idx)} {getattr(i, 'topic', '(unknown topic)')}\n\n"
                f"_(section omitted — formatting error: {exc!r})_\n"
            )
    full = "\n\n---\n\n".join(sections)

    safe_name = f"usgaap-ifrs-comparison-{run.id}"
    if payload.format == "pdf":
        # render_pdf_bytes is CPU-bound (fpdf2 walks every line, shapes
        # glyphs, embeds a Unicode TTF). Running it inline blocks the
        # event loop for the duration — long enough on a multi-issue
        # Hebrew memo that Render's edge times out the request with 502.
        # Off-thread it + cap with asyncio.wait_for so a pathological
        # render can't pin the worker forever.
        #
        # render_pdf_bytes is guaranteed not to raise (it has its own
        # stub-PDF fallback for catastrophic failures, including
        # BaseException-derived runtime panics like
        # pyo3_runtime.PanicException from cryptography's Rust bindings).
        # The remaining handlers are defense-in-depth: if a future change
        # to the renderer regresses the no-raise contract — including via
        # a BaseException path that the previous `except Exception` here
        # would have leaked as the opaque "הייצוא נכשל (500)" pill the
        # user reported on Render — we still hand back a downloadable
        # file with the failure reason inside rather than a 500. The
        # bare `raise` clause keeps process / task control signals
        # propagating so uvicorn can shut the worker down and ASGI
        # cancellation cleans up properly.
        try:
            pdf_bytes = await asyncio.wait_for(
                asyncio.to_thread(render_pdf_bytes, full, locale=locale),
                timeout=300.0,
            )
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError, GeneratorExit):
            raise
        except TimeoutError as exc:
            raise ApiError(
                status=504,
                code="pdf_timeout",
                detail="PDF rendering took longer than 5 minutes — try the markdown export instead",
            ) from exc
        except BaseException as exc:
            logger.exception("pdf render unexpectedly raised for run %s", run_id)
            from app.audit.workpapers.renderer import _stub_pdf

            pdf_bytes = _stub_pdf(f"PDF render crashed: {exc!r}")
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


# ─────────────── memo i18n + translation ───────────────
#
# When the user has selected Hebrew (locale=he on the export request),
# the memo's section headings + LLM-generated prose (summaries, verifier
# output, differences, conversion impact) are rendered in Hebrew, while
# verbatim cited quotes from US GAAP / IFRS standards stay in their
# source language (auditors need the original text for citation
# integrity). User-document quotes also stay verbatim — they were
# uploaded in their native language to begin with.

_MEMO_STRINGS = {
    "en": {
        "draft_banner": "**DRAFT — REQUIRES PARTNER REVIEW**",
        "title": "USGAAP <> IFRS comparison",
        "detected_framework": "Detected framework",
        "generated": "Generated",
        "confidence": "Detection confidence",
        "rationale": "Rationale",
        "current_treatment": "Current treatment (from your document)",
        "source_paragraphs_user": "Source paragraphs from your document",
        "us_gaap_treatment": "US GAAP treatment",
        "source_paragraphs_gaap": "Source paragraphs from US GAAP standards",
        "ifrs_treatment": "IFRS treatment",
        "source_paragraphs_ifrs": "Source paragraphs from IFRS standards",
        "verifier_us": "Verifier agent (US GAAP)",
        "verifier_ifrs": "Verifier agent (IFRS)",
        "key_differences": "Key differences",
        "conversion_impact": "Conversion impact",
        "none_retrieved": "_(none retrieved — see verifier note below)_",
        "no_current_summary": "_(no current treatment summary)_",
        "no_gaap_retrieved": "_(no US GAAP standards retrieved)_",
        "no_ifrs_retrieved": "_(no IFRS standards retrieved)_",
        "see_summaries_above": "_See side-by-side summaries above._",
        "source_label": "source",
    },
    "he": {
        "draft_banner": "**טיוטה — דורש סקירת שותף**",
        "title": "השוואת USGAAP <> IFRS",
        "detected_framework": "תקן שזוהה",
        "generated": "נוצר",
        "confidence": "ביטחון הזיהוי",
        "rationale": "נימוק",
        "current_treatment": "טיפול נוכחי (מהמסמך שלך)",
        "source_paragraphs_user": "פסקאות מקור מהמסמך שלך",
        "us_gaap_treatment": "טיפול לפי US GAAP",
        "source_paragraphs_gaap": "פסקאות מקור מתקני US GAAP",
        "ifrs_treatment": "טיפול לפי IFRS",
        "source_paragraphs_ifrs": "פסקאות מקור מתקני IFRS",
        "verifier_us": "סוכן אימות (US GAAP)",
        "verifier_ifrs": "סוכן אימות (IFRS)",
        "key_differences": "הבדלים מרכזיים",
        "conversion_impact": "השפעת ההמרה",
        "none_retrieved": "_(לא אותרו — ראו הערת האימות בהמשך)_",
        "no_current_summary": "_(אין סיכום של הטיפול הנוכחי)_",
        "no_gaap_retrieved": "_(לא אותרו תקני US GAAP)_",
        "no_ifrs_retrieved": "_(לא אותרו תקני IFRS)_",
        "see_summaries_above": "_ראו את הסיכומים צד-לצד למעלה._",
        "source_label": "מקור",
    },
}


async def _maybe_translate_issue(
    i: ComparisonIssue, locale: str,
) -> dict[str, str | None]:
    """Return a dict of the issue's prose fields, translated to Hebrew when
    locale=='he'. Verbatim quotes (current_user_cites, gaap_citations,
    ifrs_citations) are NEVER translated — they stay in their source
    language so citation integrity is preserved for the auditor.
    """
    fields: dict[str, str | None] = {
        "current_summary": i.current_summary,
        "gaap_summary": i.gaap_summary,
        "ifrs_summary": i.ifrs_summary,
        "differences": i.differences,
        "conversion_impact": i.conversion_impact,
        "gaap_verification": i.gaap_verification,
        "ifrs_verification": i.ifrs_verification,
    }
    if locale != "he":
        return fields
    to_translate = {k: v for k, v in fields.items() if v}
    translated = await _translate_to_hebrew({k: v for k, v in to_translate.items() if v})
    for k, v in translated.items():
        fields[k] = v
    return fields


def _format_issue_section(
    i: ComparisonIssue,
    prose: dict[str, str | None],
    locale: str = "en",
) -> str:
    """Render one issue as a self-contained markdown section with the
    EXACT source paragraphs (verbatim quotes) inline next to each side's
    implementation summary, plus the verifier agent's correctness report.

    ``prose`` carries the (possibly translated) summary / verifier /
    differences / conversion_impact text. Verbatim cited quotes come
    straight from ``i.*_citations`` and are NEVER translated.
    """
    s = _MEMO_STRINGS.get(locale, _MEMO_STRINGS["en"])

    def _txt(key: str, default: str = "") -> str:
        """Pull a string from `prose`, coercing non-strings to default.

        A stray non-str value (an LLM translation returning a list or
        number for a key) would otherwise crash assembly with
        ``TypeError: can only concatenate str (not "list") to str`` at
        the ``+ "\\n"`` below, which surfaces as a 500."""
        v = prose.get(key)
        return v if isinstance(v, str) else default

    parts: list[str] = []
    parts.append(f"## #{i.seq} {i.topic}\n")

    # --- Current treatment from the user's document ---
    parts.append(f"### {s['current_treatment']}\n")
    parts.append((_txt("current_summary") or s["no_current_summary"]) + "\n")
    user_cites = i.current_user_cites if isinstance(i.current_user_cites, list) else []
    if user_cites:
        parts.append(f"#### {s['source_paragraphs_user']}\n")
        for c in user_cites:
            if not isinstance(c, dict):
                # Tolerant of malformed JSONB rows: best-effort stringify.
                parts.append(f"> {c!r}")
                parts.append("")
                continue
            anchor = c.get("anchor") or c.get("ref") or "?"
            quote_raw = c.get("quote")
            quote = quote_raw.strip() if isinstance(quote_raw, str) else ""
            parts.append(f"> **{anchor}**")
            if quote:
                parts.append(f"> {quote}")
            parts.append("")  # blank line between cites

    # --- US GAAP side ---
    parts.append(f"### {s['us_gaap_treatment']}\n")
    parts.append((_txt("gaap_summary") or s["no_gaap_retrieved"]) + "\n")
    parts.append(f"#### {s['source_paragraphs_gaap']}\n")
    parts.append(_format_inline_cites(i.gaap_citations, locale))
    if _txt("gaap_verification"):
        parts.append(f"#### {s['verifier_us']}\n")
        parts.append(_txt("gaap_verification") + "\n")

    # --- IFRS side ---
    parts.append(f"### {s['ifrs_treatment']}\n")
    parts.append((_txt("ifrs_summary") or s["no_ifrs_retrieved"]) + "\n")
    parts.append(f"#### {s['source_paragraphs_ifrs']}\n")
    parts.append(_format_inline_cites(i.ifrs_citations, locale))
    if _txt("ifrs_verification"):
        parts.append(f"#### {s['verifier_ifrs']}\n")
        parts.append(_txt("ifrs_verification") + "\n")

    # --- Differences + conversion impact ---
    parts.append(f"### {s['key_differences']}\n")
    parts.append((_txt("differences") or s["see_summaries_above"]) + "\n")
    if _txt("conversion_impact"):
        parts.append(f"### {s['conversion_impact']}\n")
        parts.append(_txt("conversion_impact") + "\n")

    return "\n".join(parts)


def _format_inline_cites(cites: object, locale: str = "en") -> str:
    """Each cited paragraph is rendered as a labelled blockquote so it
    visually sits next to the summary it backs. Verbatim quotes are
    preserved in full — no truncation, no translation (citation integrity
    requires the original source language).

    Only the ``source:`` label is localized.

    Tolerant of malformed input: JSONB columns can technically hold any
    JSON value, so we coerce non-dict entries (and non-list inputs) to
    a stringified blockquote instead of crashing with
    ``AttributeError: 'NoneType' object has no attribute 'get'``.
    """
    s = _MEMO_STRINGS.get(locale, _MEMO_STRINGS["en"])
    if not cites or not isinstance(cites, list):
        return s["none_retrieved"] + "\n"
    out: list[str] = []
    for c in cites:
        if not isinstance(c, dict):
            out.append(f"> {c!r}")
            out.append("")
            continue
        std = c.get("standard") or "(no standard)"
        para = c.get("paragraph")
        url = c.get("url") or ""
        quote_raw = c.get("quote")
        quote = quote_raw.strip() if isinstance(quote_raw, str) else ""
        header = f"> **{std}**"
        if para:
            header += f" ¶{para}"
        out.append(header)
        if quote:
            out.append(f"> _\"{quote}\"_")
        if url:
            out.append(f"> {s['source_label']}: {url}")
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
