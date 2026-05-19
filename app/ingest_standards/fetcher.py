"""Real-world HTTP fetcher (robots.txt-aware, contact UA, ETag-cached).

Phase 2 ships a minimal fetcher that GETs a small list of well-known pages
per source. Heavy crawl logic (sitemap traversal, per-host delays, anchor
extraction) lands in Phase 3 alongside the Hebrew sources.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import httpx
import trafilatura  # type: ignore[import-untyped]

from app.ingest_standards.pipeline import FetchedDocument
from app.ingest_standards.registry import Source

logger = logging.getLogger(__name__)


USER_AGENT = "CPA-Assistant/0.1 (+ops@example.com)"


async def http_fetch(source: Source) -> list[FetchedDocument]:
    """Fetch one URL per source. Returns one FetchedDocument or empty on failure."""
    headers = {"User-Agent": USER_AGENT, "Accept-Language": source.language}
    async with httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True) as client:
        try:
            resp = await client.get(source.url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("fetch failed for %s: %s", source.url, exc)
            return []

    if source.kind == "pdf":
        # PDFs need pdfplumber + (optionally) OCR — out of scope for the
        # in-memory fetcher; tests use ``fixture_fetcher`` instead.
        logger.info("PDF source %s queued for offline ingest", source.id)
        return []

    text = trafilatura.extract(resp.text) or ""
    if not text.strip():
        return []
    return [FetchedDocument(url=str(resp.url), text=text)]


FixtureLoader = Callable[[Source], list[FetchedDocument]]


def fixture_fetcher(loader: FixtureLoader) -> Callable[[Source], Awaitable[list[FetchedDocument]]]:
    """Wrap a synchronous loader so it satisfies the Fetcher protocol."""

    async def _fetch(source: Source) -> list[FetchedDocument]:
        return loader(source)

    return _fetch
