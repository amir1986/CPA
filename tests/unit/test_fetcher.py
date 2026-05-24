"""Integration-style tests for the standards fetcher using httpx.MockTransport."""

from __future__ import annotations

import httpx
import pytest

from app.ingest_standards.fetcher import FetchOptions, http_fetch
from app.ingest_standards.registry import Source
from app.storage.s3 import reset_object_store

SOURCE = Source(
    id="fixture_src",
    name="Fixture HTML source",
    url="https://x.test/",
    corpus_type="accounting",
    jurisdiction="US",
    language="en",
    kind="html",
    licence="fixture",
)


HTML_PAGE = """<html><head><title>ASC 606</title></head>
<body><article><h1>Revenue Recognition — ASC 606-10-25-1</h1>
<p>Revenue is recognized when control transfers to the customer.</p>
</article></body></html>"""

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://x.test/page1</loc></url>
  <url><loc>https://x.test/page2</loc></url>
  <url><loc>https://x.test/outside</loc></url>
</urlset>
"""


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CPA_S3_BACKEND", "memory")
    reset_object_store()
    yield
    reset_object_store()


def _transport(handler):
    return httpx.MockTransport(handler)


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    real = httpx.AsyncClient

    class _Client(real):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("app.ingest_standards.fetcher.httpx.AsyncClient", _Client)
    monkeypatch.setattr("app.ingest_standards.discovery.httpx.AsyncClient", _Client)
    monkeypatch.setattr("app.ingest_standards.robots.httpx.AsyncClient", _Client)


@pytest.mark.asyncio
async def test_full_fetch_with_sitemap_and_etag_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        u = str(request.url)
        if u.endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if u.endswith("/sitemap.xml"):
            return httpx.Response(200, text=SITEMAP, headers={"Content-Type": "application/xml"})
        if u.endswith("/sitemap_index.xml"):
            return httpx.Response(404)
        if "/page" in u:
            return httpx.Response(
                200,
                text=HTML_PAGE,
                headers={"Content-Type": "text/html; charset=utf-8", "ETag": '"abc-123"'},
            )
        if u == "https://x.test/":
            return httpx.Response(200, text="<html><body>landing</body></html>", headers={"Content-Type": "text/html"})
        return httpx.Response(404)

    _patch_httpx(monkeypatch, _transport(handler))

    # Allow the test sitemap host through the profile allow-list.
    monkeypatch.setattr(
        "app.ingest_standards.discovery.PROFILES",
        {"fixture_src": __import__("app.ingest_standards.discovery", fromlist=["SourceProfile"]).SourceProfile(
            allowed_prefixes=("https://x.test/",), max_urls=10,
        )},
    )

    docs = await http_fetch(SOURCE, FetchOptions(global_concurrency=2, per_host_concurrency=2))
    urls = sorted({d.url for d in docs})
    assert "https://x.test/page1" in urls
    assert "https://x.test/page2" in urls
    # Outside-prefix URL was filtered.
    assert "https://x.test/outside" not in urls
    # Standard was extracted from the heading on at least one of the pages.
    assert any(d.standard == "ASC 606-10-25-1" for d in docs)

    # Round 2 — ETag conditional GETs.
    seen.clear()

    def handler2(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        u = str(request.url)
        if u.endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if u.endswith("/sitemap.xml"):
            return httpx.Response(200, text=SITEMAP, headers={"Content-Type": "application/xml"})
        if u.endswith("/sitemap_index.xml"):
            return httpx.Response(404)
        if "/page" in u:
            # We expect If-None-Match here.
            if request.headers.get("If-None-Match") == '"abc-123"':
                return httpx.Response(304)
            return httpx.Response(200, text=HTML_PAGE, headers={"Content-Type": "text/html", "ETag": '"abc-123"'})
        if u == "https://x.test/":
            return httpx.Response(200, text="<html><body>landing</body></html>", headers={"Content-Type": "text/html"})
        return httpx.Response(404)

    _patch_httpx(monkeypatch, _transport(handler2))
    docs2 = await http_fetch(SOURCE, FetchOptions(global_concurrency=2, per_host_concurrency=2))
    # 304s should still produce documents, served from cached body.
    assert {d.url for d in docs2} == {d.url for d in docs}
