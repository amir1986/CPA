"""RobotsGate behavior tests."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.ingest_standards.robots import RobotsGate


def _patched_client(responses: dict[str, httpx.Response]):
    """Return a context manager that patches httpx.AsyncClient to serve canned responses."""
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, *args, **kwargs):
            if url in responses:
                return responses[url]
            raise httpx.RequestError("not stubbed", request=httpx.Request("GET", url))

    return patch("app.ingest_standards.robots.httpx.AsyncClient", _Client)


def _ok(body: str, *, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=body, request=httpx.Request("GET", "http://x"))


@pytest.mark.asyncio
async def test_allow_when_robots_404() -> None:
    with _patched_client({"https://x.test/robots.txt": _ok("", status=404)}):
        gate = RobotsGate(user_agent="t")
        assert await gate.can_fetch("https://x.test/page") is True


@pytest.mark.asyncio
async def test_disallow_directives_honored() -> None:
    body = "User-agent: *\nDisallow: /private/\nCrawl-delay: 2\n"
    with _patched_client({"https://x.test/robots.txt": _ok(body)}):
        gate = RobotsGate(user_agent="t")
        assert await gate.can_fetch("https://x.test/public/p1") is True
        assert await gate.can_fetch("https://x.test/private/p1") is False
        assert await gate.crawl_delay("https://x.test/page") == 2.0


@pytest.mark.asyncio
async def test_5xx_treated_as_disallow() -> None:
    with _patched_client({"https://x.test/robots.txt": _ok("", status=503)}):
        gate = RobotsGate(user_agent="t")
        assert await gate.can_fetch("https://x.test/p1") is False


@pytest.mark.asyncio
async def test_cached_within_ttl() -> None:
    calls: list[str] = []

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, *a, **k):
            calls.append(url)
            return _ok("User-agent: *\nAllow: /\n")

    with patch("app.ingest_standards.robots.httpx.AsyncClient", _Client):
        gate = RobotsGate(user_agent="t", ttl_seconds=60)
        await gate.can_fetch("https://x.test/p1")
        await gate.can_fetch("https://x.test/p2")
    # one robots.txt fetch served both requests
    assert calls.count("https://x.test/robots.txt") == 1


@pytest.mark.asyncio
async def test_request_error_defaults_to_allow_all() -> None:
    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, *a, **k):
            raise httpx.RequestError("boom", request=httpx.Request("GET", url))

    with patch("app.ingest_standards.robots.httpx.AsyncClient", _Client):
        gate = RobotsGate(user_agent="t")
        assert await gate.can_fetch("https://x.test/p1") is True
