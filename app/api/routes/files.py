"""File upload, list, get, delete — scoped to the principal's firm."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends, File as FileParam, Form, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import RequestPrincipal, current_principal
from app.api.errors import ApiError
from app.api.routes.engagements import ensure_in_firm
from app.api.schemas.engagement import FileListOut, FileOut
from app.db.models.files import File, FileKind, ParsedStatus
from app.db.session import get_session, get_sessionmaker
from app.storage.paths import raw_key, s3_uri
from app.storage.s3 import get_object_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/engagements/{engagement_id}/files", tags=["files"])

MAX_FILE_SIZE = 200 * 1024 * 1024   # 200 MB per upload — large for scanned PDFs


def _out(f: File) -> FileOut:
    return FileOut(
        id=str(f.id),
        engagement_id=str(f.engagement_id),
        kind=f.kind.value,
        original_name=f.original_name,
        s3_uri=f.s3_uri,
        sha256=f.sha256,
        mime=f.mime,
        size=f.size,
        parsed_status=f.parsed_status.value,
        parsed_summary=f.parsed_summary,
        created_at=f.created_at,
    )


@router.get("", response_model=FileListOut)
async def list_files(
    engagement_id: uuid.UUID,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> FileListOut:
    await ensure_in_firm(engagement_id, principal, session)
    total = await session.scalar(
        select(func.count(File.id)).where(File.engagement_id == engagement_id)
    )
    items = (
        await session.scalars(
            select(File).where(File.engagement_id == engagement_id).order_by(File.created_at.desc())
        )
    ).all()
    return FileListOut(items=[_out(f) for f in items], total=int(total or 0))


@router.post("", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    engagement_id: uuid.UUID,
    file: UploadFile = FileParam(...),
    kind: str = Form(...),
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> FileOut:
    await ensure_in_firm(engagement_id, principal, session)

    try:
        file_kind = FileKind(kind)
    except ValueError as exc:
        raise ApiError(status=400, code="bad_request", detail=f"unknown kind: {kind}") from exc

    body = await file.read()
    if len(body) == 0:
        raise ApiError(status=400, code="empty_file", detail="uploaded file is empty")
    if len(body) > MAX_FILE_SIZE:
        raise ApiError(status=413, code="too_large", detail="file exceeds 200 MB limit")

    sha = hashlib.sha256(body).hexdigest()
    mime = file.content_type or mimetypes.guess_type(file.filename or "")[0]
    file_id = uuid.uuid4()

    key = raw_key(engagement_id=engagement_id, file_id=file_id, filename=file.filename or "upload")
    store = get_object_store()
    await store.put(key, body, content_type=mime)

    row = File(
        id=file_id,
        engagement_id=engagement_id,
        kind=file_kind,
        original_name=file.filename or "upload",
        s3_uri=s3_uri(key),
        sha256=sha,
        mime=mime,
        size=len(body),
        parsed_status=ParsedStatus.queued,
        uploaded_by=principal.user_id,
    )
    session.add(row)
    await session.flush()
    logger.info(
        "file uploaded: engagement=%s file=%s kind=%s size=%d",
        engagement_id,
        file_id,
        kind,
        len(body),
    )
    return _out(row)


@router.get("/{file_id}", response_model=FileOut)
async def get_file(
    engagement_id: uuid.UUID,
    file_id: uuid.UUID,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> FileOut:
    await ensure_in_firm(engagement_id, principal, session)
    f = await session.get(File, file_id)
    if f is None or f.engagement_id != engagement_id:
        raise ApiError(status=404, code="not_found", detail="file not found")
    return _out(f)


@router.get("/{file_id}/status/stream")
async def file_status_stream(
    engagement_id: uuid.UUID,
    file_id: uuid.UUID,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """SSE: emits the file's parsed_status until it lands on done or failed."""
    await ensure_in_firm(engagement_id, principal, session)
    f = await session.get(File, file_id)
    if f is None or f.engagement_id != engagement_id:
        raise ApiError(status=404, code="not_found", detail="file not found")

    async def gen() -> AsyncIterator[bytes]:
        factory = get_sessionmaker()
        last: str | None = None
        for _ in range(120):  # ≤ 2 minutes, polling every 1s
            async with factory() as s2:
                row = await s2.get(File, file_id)
                if row is None:
                    yield f"event: error\ndata: {json.dumps({'detail': 'file vanished'})}\n\n".encode()
                    return
                cur = row.parsed_status.value
            if cur != last:
                yield f"event: status\ndata: {json.dumps({'status': cur})}\n\n".encode()
                last = cur
            if cur in {"done", "failed"}:
                yield b"event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(1)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    engagement_id: uuid.UUID,
    file_id: uuid.UUID,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> None:
    await ensure_in_firm(engagement_id, principal, session)
    f = await session.get(File, file_id)
    if f is None or f.engagement_id != engagement_id:
        raise ApiError(status=404, code="not_found", detail="file not found")
    # Strip the s3:// prefix to recover the key.
    key = f.s3_uri.split("/", 3)[-1] if f.s3_uri.startswith("s3://") else f.s3_uri
    store = get_object_store()
    await store.delete(key)
    await session.delete(f)
