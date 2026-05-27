"""Digital-PDF text extractor.

Returns a list of ``(anchor, text)`` pairs where ``anchor`` is a
human-readable label like ``"page=3"``. Scanned PDFs return mostly-empty
text — the caller is expected to detect that and surface an OCR-not-yet-
supported banner rather than feed the empty result to the LLM.
"""

from __future__ import annotations

import io
from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractedSpan:
    anchor: str  # e.g. "page=3" or "paragraph=14"
    text: str


def extract_pdf_text(body: bytes) -> list[ExtractedSpan]:
    try:
        import pdfplumber  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover — install [parse] extras
        raise RuntimeError("pdfplumber not installed (pip install 'cpa[parse]')") from exc

    spans: list[ExtractedSpan] = []
    with pdfplumber.open(io.BytesIO(body)) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception:
                text = ""
            spans.append(ExtractedSpan(anchor=f"page={idx}", text=text))
    return spans


def is_likely_scanned(spans: list[ExtractedSpan], min_chars_per_page: int = 50) -> bool:
    """Heuristic: if every page has fewer than ``min_chars_per_page`` characters,
    the PDF is almost certainly a scanned image and pdfplumber is the wrong
    extractor. Callers should fail loudly rather than silently produce zero
    issues from empty text.
    """
    if not spans:
        return True
    return all(len(s.text) < min_chars_per_page for s in spans)
