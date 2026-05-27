"""robots.txt fetcher + parser with a small TTL cache.

We use ``urllib.robotparser`` for parsing and run the actual HTTP fetch
through ``httpx.AsyncClient`` so the User-Agent + timeout match the rest
of the crawler.

The cache is keyed by URL origin (scheme + host + port) and lives in
process memory — sufficient because each ingest run is short-lived and
the source list is small.

If robots.txt is unreachable (network error, 404), we honor the IETF
RFC 9309 recommendation: assume *allow all*, but log it. (5xx is treated
as "disallow all" to be safe.)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)


_DEFAULT_TTL = 3600.0   # 1 hour


@dataclass
class _Entry:
    parser: RobotFileParser
    crawl_delay: float
    expires_at: float
    allow_all: bool


class RobotsGate:
    def __init__(
        self,
        *,
        user_agent: str,
        ttl_seconds: float = _DEFAULT_TTL,
        timeout: float = 10.0,
    ) -> None:
        self._user_agent = user_agent
        self._ttl = ttl_seconds
        self._timeout = timeout
        self._cache: dict[str, _Entry] = {}

    def _origin(self, url: str) -> str:
        p = urlparse(url)
        port = f":{p.port}" if p.port else ""
        return f"{p.scheme}://{p.hostname}{port}"

    async def _fetch(self, origin: str) -> _Entry:
        url = f"{origin}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(url)

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": self._user_agent},
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
        except httpx.RequestError as exc:
            logger.info("robots: %s unreachable (%s) — defaulting to allow all", url, exc)
            return _Entry(parser=parser, crawl_delay=0.0, expires_at=time.time() + self._ttl, allow_all=True)

        if resp.status_code in (401, 403):
            # Per RFC 9309 §2.3: full disallow.
            parser.parse(["User-agent: *", "Disallow: /"])
        elif 500 <= resp.status_code < 600:
            # Conservative: treat 5xx as disallow until cache expires.
            parser.parse(["User-agent: *", "Disallow: /"])
            logger.info("robots: %s returned %d — treating as disallow", url, resp.status_code)
        elif resp.status_code == 200:
            parser.parse(resp.text.splitlines())
        else:
            # 404 / 410: allow all.
            return _Entry(parser=parser, crawl_delay=0.0, expires_at=time.time() + self._ttl, allow_all=True)

        crawl_delay = parser.crawl_delay(self._user_agent) or 0.0
        return _Entry(parser=parser, crawl_delay=float(crawl_delay), expires_at=time.time() + self._ttl, allow_all=False)

    async def _entry(self, url: str) -> _Entry:
        origin = self._origin(url)
        cached = self._cache.get(origin)
        if cached and cached.expires_at > time.time():
            return cached
        entry = await self._fetch(origin)
        self._cache[origin] = entry
        return entry

    async def can_fetch(self, url: str) -> bool:
        entry = await self._entry(url)
        if entry.allow_all:
            return True
        return entry.parser.can_fetch(self._user_agent, url)

    async def crawl_delay(self, url: str) -> float:
        entry = await self._entry(url)
        return entry.crawl_delay
