"""Production HTTP fetcher for the standards crawl.

Key behaviors:
- robots.txt awareness (RobotsGate; defaults to allow when robots is 404 /
  unreachable, but disallows on 5xx until cache expires).
- Per-host crawl-delay honored (greater of robots' delay and a per-host
  asyncio.Lock-protected min interval).
- Concurrency-limited via two semaphores: a global cap and a per-host cap.
- Content-stable caching in object storage at corpus_cache/{source_id}/{sha}:
  - SHA1 of (url + ETag) is the cache key.
  - On hit, we send ``If-None-Match``; 304 short-circuits to the cached body.
- HTML or PDF dispatched by content-type; Hebrew sources get RTL fix-ups.
- Each fetched document yields ``FetchedDocument(url, text, standard?, paragraph?)``
  ready for the chunker.

The fetcher is designed for short ingest runs (≤ a few minutes per source).
Long crawls should run in a Job/CronJob and resume by re-walking the
discovery output.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import urlparse

import httpx

from app.ingest_standards.discovery import USER_AGENT, discover_urls
from app.ingest_standards.parsers.html_parser import parse_html
from app.ingest_standards.parsers.pdf_parser import parse_pdf
from app.ingest_standards.pipeline import FetchedDocument
from app.ingest_standards.registry import Source
from app.ingest_standards.robots import RobotsGate
from app.storage.paths import corpus_cache_key
from app.storage.s3 import get_object_store

logger = logging.getLogger(__name__)


# ──────────────── small helpers ────────────────


def _host(url: str) -> str:
    return urlparse(url).hostname or ""


def _cache_key(source_id: str, url: str, etag: str | None) -> str:
    """Stable cache key built from URL + ETag (so a new ETag → new key)."""
    base = f"{url}|{etag or ''}"
    return corpus_cache_key(source_id=source_id, sha=hashlib.sha1(base.encode()).hexdigest())


def _index_key(source_id: str) -> str:
    return f"corpus_cache/{source_id}/_index.json"


# ──────────────── ETag index ────────────────


async def _load_index(source_id: str) -> dict[str, dict[str, object]]:
    store = get_object_store()
    try:
        raw = await store.get(_index_key(source_id))
    except Exception:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


async def _save_index(source_id: str, index: dict[str, dict[str, object]]) -> None:
    store = get_object_store()
    await store.put(
        _index_key(source_id),
        json.dumps(index, sort_keys=True).encode("utf-8"),
        content_type="application/json",
    )


# ──────────────── host rate limiter ────────────────


class _HostThrottle:
    """Greater of robots crawl-delay and a per-host async lock with min interval."""

    def __init__(self, default_min_interval: float = 0.5) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_at: dict[str, float] = {}
        self._min = default_min_interval

    async def wait(self, host: str, crawl_delay: float) -> None:
        delay = max(self._min, float(crawl_delay or 0.0))
        lock = self._locks[host]
        async with lock:
            last = self._last_at.get(host, 0.0)
            now = time.monotonic()
            gap = now - last
            if gap < delay:
                await asyncio.sleep(delay - gap)
            self._last_at[host] = time.monotonic()


# ──────────────── main entry ────────────────


@dataclass
class FetchOptions:
    global_concurrency: int = 4
    per_host_concurrency: int = 2
    timeout: float = 30.0
    user_agent: str = USER_AGENT
    max_bytes: int = 4 * 1024 * 1024


async def http_fetch(source: Source, opts: FetchOptions | None = None) -> list[FetchedDocument]:
    opts = opts or FetchOptions()
    urls = await discover_urls(source, user_agent=opts.user_agent, timeout=opts.timeout)
    if not urls:
        logger.info("ingest: %s discovered 0 URLs", source.id)
        return []

    robots = RobotsGate(user_agent=opts.user_agent)
    throttle = _HostThrottle()
    global_sem = asyncio.Semaphore(opts.global_concurrency)
    host_sems: dict[str, asyncio.Semaphore] = defaultdict(
        lambda: asyncio.Semaphore(opts.per_host_concurrency)
    )
    index = await _load_index(source.id)

    headers = {
        "User-Agent": opts.user_agent,
        "Accept-Language": source.language,
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9",
    }

    async with httpx.AsyncClient(timeout=opts.timeout, headers=headers, follow_redirects=True) as client:
        async def _one(url: str) -> FetchedDocument | None:
            if not await robots.can_fetch(url):
                logger.info("robots: %s disallowed", url)
                return None
            host = _host(url)
            async with global_sem, host_sems[host]:
                await throttle.wait(host, await robots.crawl_delay(url))
                return await _fetch_one(client, source, url, index, opts)

        results = await asyncio.gather(*[_one(u) for u in urls], return_exceptions=False)

    await _save_index(source.id, index)
    docs = [r for r in results if r is not None]
    logger.info("ingest: %s fetched %d / %d", source.id, len(docs), len(urls))
    return docs


async def _fetch_one(
    client: httpx.AsyncClient,
    source: Source,
    url: str,
    index: dict[str, dict[str, object]],
    opts: FetchOptions,
) -> FetchedDocument | None:
    cached = index.get(url, {})
    cached_etag = cached.get("etag") if isinstance(cached.get("etag"), str) else None
    req_headers: dict[str, str] = {}
    if cached_etag:
        req_headers["If-None-Match"] = str(cached_etag)

    try:
        resp = await client.get(url, headers=req_headers)
    except httpx.RequestError as exc:
        logger.info("fetch failed for %s: %s", url, exc)
        return None

    if resp.status_code == 304 and cached_etag:
        store = get_object_store()
        try:
            body = await store.get(_cache_key(source.id, url, cached_etag))
        except Exception as exc:
            logger.info("cache miss-after-304 for %s: %s", url, exc)
            return None
        return _parse_doc(source, url, body, resp.headers.get("Content-Type") or "")

    if resp.status_code != 200:
        logger.info("non-200 for %s: %d", url, resp.status_code)
        return None

    if int(resp.headers.get("Content-Length", "0") or "0") > opts.max_bytes:
        logger.info("oversized response for %s (skipping)", url)
        return None

    body = resp.content
    if len(body) > opts.max_bytes:
        logger.info("oversized body for %s (skipping)", url)
        return None

    etag = resp.headers.get("ETag")
    if etag:
        store = get_object_store()
        await store.put(
            _cache_key(source.id, url, etag),
            body,
            content_type=resp.headers.get("Content-Type"),
        )
        index[url] = {"etag": etag, "cached_at": time.time()}

    return _parse_doc(source, url, body, resp.headers.get("Content-Type") or "")


def _parse_doc(source: Source, url: str, body: bytes, content_type: str) -> FetchedDocument | None:
    ct = content_type.split(";")[0].strip().lower()
    is_hebrew = source.language == "he"

    if "pdf" in ct or source.kind == "pdf" or url.lower().endswith(".pdf"):
        parsed = parse_pdf(body, is_hebrew=is_hebrew, ocr=False)
        if not parsed.text:
            logger.info("empty PDF text for %s (needs_ocr=%s)", url, parsed.needs_ocr)
            return None
        return FetchedDocument(url=url, text=parsed.text)

    try:
        raw = body.decode("utf-8", errors="replace")
    except Exception:
        return None
    parsed_html = parse_html(raw)
    if not parsed_html.text:
        return None
    return FetchedDocument(
        url=url,
        text=parsed_html.text,
        standard=parsed_html.standard,
        paragraph=parsed_html.paragraph,
    )


# ──────────────── fixture path (kept for tests / pipeline backward-compat) ────────────────


FixtureLoader = Callable[[Source], list[FetchedDocument]]


def fixture_fetcher(loader: FixtureLoader) -> Callable[[Source], Awaitable[list[FetchedDocument]]]:
    """Wrap a synchronous fixture loader so it satisfies the Fetcher protocol."""

    async def _fetch(source: Source) -> list[FetchedDocument]:
        return loader(source)

    return _fetch
