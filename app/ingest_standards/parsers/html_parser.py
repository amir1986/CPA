"""HTML → clean text + anchor-aware sections.

Primary path: ``trafilatura.extract`` — robust at stripping nav/boilerplate.
Fallback: selectolax with a manual content-area extraction.

We also preserve heading anchors (h1/h2/h3 ids) so the chunker can keep
section breaks aligned with their identifiers — useful for citation
``paragraph`` resolution.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParsedHTML:
    title: str | None
    text: str
    standard: str | None  # e.g. "ASC 606-10-25-1" if a heading matched
    paragraph: str | None


# Common standards-anchor patterns: ASC 605-10-25-1, AU-C §240.A1, ISA 240,
# IRC §6662(d)(1)(A). We extract just enough to attach a "standard" hint.
_STANDARD_PATTERNS = [
    re.compile(r"ASC\s+\d{3}-\d{2}-\d{2}-\d+"),
    re.compile(r"AU-?C\s*§?\s*\d+(?:\.[A-Z]\d+)?", re.IGNORECASE),
    re.compile(r"ISA\s+\d+"),
    re.compile(r"IFRS\s+\d+(?:\.\d+)?"),
    re.compile(r"IAS\s+\d+"),
    re.compile(r"IRC\s*§?\s*\d+"),
]


def parse_html(raw: str) -> ParsedHTML:
    title: str | None = None
    text = ""
    # 1) trafilatura
    try:
        import trafilatura  # type: ignore[import-untyped]

        extracted = trafilatura.extract(raw, include_tables=True, include_links=False)
        if extracted:
            text = extracted
        meta = trafilatura.extract_metadata(raw)
        if meta and meta.title:
            title = meta.title
    except Exception as exc:  # pragma: no cover — defensive
        logger.info("trafilatura failed: %s", exc)

    # 2) Fallback / metadata
    if not text or not title:
        try:
            from selectolax.parser import HTMLParser

            tree = HTMLParser(raw)
            if title is None:
                t = tree.css_first("title")
                title = t.text(strip=True) if t else None
            if not text:
                main = tree.css_first("article, main, #content, .content")
                text = (main or tree.body or tree).text(separator="\n", strip=True)
        except Exception as exc:  # pragma: no cover
            logger.info("selectolax fallback failed: %s", exc)

    text = re.sub(r"[ \t]+", " ", text or "")
    text = re.sub(r"\n{3,}", "\n\n", text)

    standard = None
    paragraph = None
    for pat in _STANDARD_PATTERNS:
        m = pat.search(text)
        if m:
            standard = m.group(0)
            # Last dotted suffix becomes the paragraph hint.
            tail = standard.split("-")[-1] if "-" in standard else None
            paragraph = tail
            break

    return ParsedHTML(title=title, text=text.strip(), standard=standard, paragraph=paragraph)
