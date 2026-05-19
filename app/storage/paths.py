"""Canonical S3 key builders.

These mirror the layout documented in the plan:
- ``raw/{engagement_id}/{file_id}/{original_filename}`` — original uploads
- ``parsed/{engagement_id}/{file_id}.json`` — canonicalized representation
- ``workpapers/{engagement_id}/{workpaper_id}.md`` and ``.pdf``
- ``corpus_cache/{source_id}/{sha}`` — standards-ingest fetcher cache
"""

from __future__ import annotations

from uuid import UUID

from app.config import get_settings


def raw_key(*, engagement_id: UUID, file_id: UUID, filename: str) -> str:
    safe = filename.replace("/", "_").replace("\\", "_")
    return f"raw/{engagement_id}/{file_id}/{safe}"


def parsed_key(*, engagement_id: UUID, file_id: UUID) -> str:
    return f"parsed/{engagement_id}/{file_id}.json"


def workpaper_md_key(*, engagement_id: UUID, workpaper_id: UUID) -> str:
    return f"workpapers/{engagement_id}/{workpaper_id}.md"


def workpaper_pdf_key(*, engagement_id: UUID, workpaper_id: UUID) -> str:
    return f"workpapers/{engagement_id}/{workpaper_id}.pdf"


def corpus_cache_key(*, source_id: str, sha: str) -> str:
    return f"corpus_cache/{source_id}/{sha}"


def s3_uri(key: str) -> str:
    """Return a ``s3://bucket/key`` URI for storage in the DB."""
    return f"s3://{get_settings().s3_bucket}/{key}"
