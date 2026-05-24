"""Per-source URL discovery.

Given a source, return up to ``max_urls`` candidate URLs to fetch.

Discovery strategies (tried in order):
1. **Source-specific:** a small registry of patterns (e.g. ``us_irc_cornell``
   knows how to enumerate Title 26 chapter listing pages).
2. **Sitemap:** parse ``/sitemap.xml`` / ``/sitemap_index.xml``, filter by
   the source's URL prefix.
3. **Landing-page anchor walk:** fetch the landing URL, extract anchor
   hrefs via selectolax, keep those whose host == landing host and
   path starts with one of the source's allowed prefixes.

Every discovered URL is normalized (query-string and fragment stripped)
and deduped before return.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse
from xml.etree import ElementTree as ET

import httpx

from app.ingest_standards.registry import Source

logger = logging.getLogger(__name__)

USER_AGENT = "CPA-Assistant/0.1 (+ops@example.com)"


@dataclass(frozen=True)
class SourceProfile:
    """Allow-list of URL prefixes + how many URLs to fetch per run."""

    allowed_prefixes: tuple[str, ...]
    max_urls: int = 30


# Per-source profiles. The crawler restricts both sitemap and anchor
# discovery to these prefixes — keeps it polite and predictable.
PROFILES: dict[str, SourceProfile] = {
    "fasb_asc_public": SourceProfile(
        allowed_prefixes=(
            "https://www.fasb.org/page/",
            "https://www.fasb.org/projects/",
        ),
        max_urls=20,
    ),
    "ifrs_foundation_public": SourceProfile(
        allowed_prefixes=(
            "https://www.ifrs.org/projects/",
            "https://www.ifrs.org/issued-standards/",
        ),
        max_urls=25,
    ),
    "aicpa_au_c_public": SourceProfile(
        allowed_prefixes=("https://www.aicpa-cima.com/topic/", "https://www.aicpa-cima.com/resources/"),
        max_urls=20,
    ),
    "pcaob_as": SourceProfile(
        allowed_prefixes=("https://pcaobus.org/oversight/standards/",),
        max_urls=30,
    ),
    "iaasb_isa": SourceProfile(
        allowed_prefixes=("https://www.iaasb.org/publications/",),
        max_urls=20,
    ),
    "il_tax_authority": SourceProfile(
        allowed_prefixes=(
            "https://www.gov.il/he/departments/israel_tax_authority",
            "https://www.gov.il/he/policies",
        ),
        max_urls=25,
    ),
    "us_irc_cornell": SourceProfile(
        allowed_prefixes=("https://www.law.cornell.edu/uscode/text/26/",),
        max_urls=30,
    ),
    "irs_pubs": SourceProfile(
        allowed_prefixes=("https://www.irs.gov/pub/", "https://www.irs.gov/forms-pubs/"),
        max_urls=25,
    ),
    "iasb_org_il_he": SourceProfile(
        allowed_prefixes=("https://www.iasb.org.il/",),
        max_urls=15,
    ),
    "il_audit_standards": SourceProfile(
        allowed_prefixes=("https://www.icpas.org.il/",),
        max_urls=15,
    ),
}


def _normalize(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/") or "/", "", "", ""))


def _allowed(url: str, profile: SourceProfile) -> bool:
    return any(url.startswith(prefix) for prefix in profile.allowed_prefixes)


async def _discover_sitemap(
    client: httpx.AsyncClient, origin: str, profile: SourceProfile
) -> list[str]:
    """Discover URLs via sitemap.xml / sitemap_index.xml. Returns at most ``max_urls``."""
    found: list[str] = []
    for sitemap_path in ("/sitemap.xml", "/sitemap_index.xml"):
        try:
            resp = await client.get(origin + sitemap_path)
        except httpx.RequestError:
            continue
        if resp.status_code != 200:
            continue
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            continue

        # Sitemap (urlset) and sitemap index both place URLs under <loc>.
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        # Try with and without ns.
        for tag in ("sm:url/sm:loc", "url/loc"):
            for elem in root.findall(tag, ns if ":" in tag else {}):
                if elem.text:
                    url = _normalize(elem.text.strip())
                    if _allowed(url, profile) and url not in found:
                        found.append(url)
                        if len(found) >= profile.max_urls:
                            return found
        # Sitemap index → recurse into nested sitemaps (one level only).
        for tag in ("sm:sitemap/sm:loc", "sitemap/loc"):
            for elem in root.findall(tag, ns if ":" in tag else {}):
                if not elem.text:
                    continue
                inner = elem.text.strip()
                try:
                    inner_resp = await client.get(inner)
                    inner_root = ET.fromstring(inner_resp.text)
                except (httpx.RequestError, ET.ParseError):
                    continue
                for loc in inner_root.findall("sm:url/sm:loc", ns):
                    if loc.text:
                        url = _normalize(loc.text.strip())
                        if _allowed(url, profile) and url not in found:
                            found.append(url)
                            if len(found) >= profile.max_urls:
                                return found
        if found:
            break
    return found


async def _discover_anchors(
    client: httpx.AsyncClient, landing_url: str, profile: SourceProfile
) -> list[str]:
    """Fetch the landing page, harvest hrefs that match the source's allow-list."""
    try:
        resp = await client.get(landing_url)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.info("landing-page fetch failed for %s: %s", landing_url, exc)
        return []

    # selectolax is fast + tolerant of malformed HTML.
    try:
        from selectolax.parser import HTMLParser

        tree = HTMLParser(resp.text)
        anchors = [a.attributes.get("href") for a in tree.css("a[href]")]
    except Exception:
        return []

    out: list[str] = []
    for href in anchors:
        if not href:
            continue
        absolute = urljoin(landing_url, href)
        normalized = _normalize(absolute)
        if _allowed(normalized, profile) and normalized not in out:
            out.append(normalized)
            if len(out) >= profile.max_urls:
                break
    return out


async def discover_urls(
    source: Source,
    *,
    user_agent: str = USER_AGENT,
    timeout: float = 30.0,
) -> list[str]:
    """Return a deduped, normalized list of URLs to fetch for ``source``."""
    profile = PROFILES.get(
        source.id,
        SourceProfile(allowed_prefixes=(source.url,), max_urls=10),
    )
    headers = {"User-Agent": user_agent, "Accept-Language": source.language}

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        origin = f"{urlparse(source.url).scheme}://{urlparse(source.url).netloc}"
        urls = await _discover_sitemap(client, origin, profile)
        if not urls:
            urls = await _discover_anchors(client, source.url, profile)
        # Always include the landing URL itself if it matches the allow-list.
        landing = _normalize(source.url)
        if _allowed(landing, profile) and landing not in urls:
            urls.insert(0, landing)
        return urls[: profile.max_urls]
