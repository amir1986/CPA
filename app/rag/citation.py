"""Citation validator.

The LLM is told to return citations as JSON tuples of (standard, paragraph,
url, quote). We do not trust it: every citation that survives must:

1. Match the (standard, paragraph, url) of one of the retrieved chunks
   (matching is lenient — paragraph alignment is optional if standard +
   url match), and
2. Have a ``quote`` that is a normalized substring of that chunk's text.

Citations that fail either check are dropped. If the answer ends up with
zero citations and the request was grounded, the caller should refuse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.models import Citation, RetrievedChunk


_NORMALIZE = re.compile(r"\s+")


def _normalize(s: str) -> str:
    return _NORMALIZE.sub(" ", s).strip().lower()


@dataclass(frozen=True)
class ValidationResult:
    kept: tuple[Citation, ...]
    dropped_reasons: tuple[str, ...]


def validate_citations(
    citations: list[dict] | list[Citation],
    retrieved: list[RetrievedChunk],
) -> ValidationResult:
    """Filter ``citations`` against ``retrieved``."""
    kept: list[Citation] = []
    dropped: list[str] = []

    norm_chunks = [
        (rc, _normalize(rc.chunk.text)) for rc in retrieved
    ]

    for raw in citations:
        if isinstance(raw, Citation):
            cite = raw
        else:
            try:
                cite = Citation(
                    standard=raw.get("standard"),
                    paragraph=raw.get("paragraph"),
                    url=raw.get("url", ""),
                    quote=raw.get("quote", ""),
                )
            except AttributeError:
                dropped.append(f"malformed citation: {raw!r}")
                continue

        if not cite.url and not cite.standard:
            dropped.append("citation has neither url nor standard")
            continue
        if not cite.quote.strip():
            dropped.append(f"citation has empty quote: {cite}")
            continue

        normalized_quote = _normalize(cite.quote)
        matched = False
        for rc, normalized_chunk in norm_chunks:
            same_url = bool(cite.url) and rc.chunk.url == cite.url
            same_standard = (
                bool(cite.standard)
                and rc.chunk.standard is not None
                and cite.standard in rc.chunk.standard
            )
            if not (same_url or same_standard):
                continue
            if normalized_quote in normalized_chunk:
                matched = True
                break

        if matched:
            kept.append(cite)
        else:
            dropped.append(
                f"quote not found in any retrieved chunk: {cite.standard or cite.url}"
            )

    return ValidationResult(kept=tuple(kept), dropped_reasons=tuple(dropped))
