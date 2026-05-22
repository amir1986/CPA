"""PDF → text. ``pdfplumber`` for digital PDFs.

Hebrew PDFs frequently render right-to-left in *visual* order even after
text extraction. We pass each line through ``python-bidi`` to recover
logical order so the chunker (and the LLM) see Hebrew text the way a
reader would type it.

Scanned PDFs (no text layer) are detected when the extracted text is
near-empty; we skip OCR by default to keep the dependency tree thin.
The caller can enable OCR by passing ``ocr=True`` (requires Tesseract
+ ``pdf2image`` to be installed in the image).
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParsedPDF:
    text: str
    page_count: int
    needs_ocr: bool


def parse_pdf(raw: bytes, *, is_hebrew: bool = False, ocr: bool = False) -> ParsedPDF:
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover
        logger.warning("pdfplumber not installed — skipping PDF")
        return ParsedPDF(text="", page_count=0, needs_ocr=True)

    pages_text: list[str] = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            t = page.extract_text() or ""
            if is_hebrew and t:
                t = _fix_rtl_lines(t)
            pages_text.append(t)
    text = "\n\n".join(p for p in pages_text if p.strip())

    needs_ocr = page_count > 0 and len(text.strip()) < 32 * page_count
    if needs_ocr and ocr:
        text = _ocr_pdf(raw, is_hebrew=is_hebrew)
        needs_ocr = False

    return ParsedPDF(text=text.strip(), page_count=page_count, needs_ocr=needs_ocr)


def _fix_rtl_lines(text: str) -> str:
    try:
        from bidi.algorithm import get_display  # type: ignore[import-not-found]
    except ImportError:
        return text
    # We invert: PDF extraction often produces visual order; we want logical.
    # ``get_display`` converts logical → visual; running it twice on already-
    # logical strings is a no-op for short ASCII runs but corrects mixed runs.
    return "\n".join(get_display(line, base_dir="R") for line in text.splitlines())


def _ocr_pdf(raw: bytes, *, is_hebrew: bool) -> str:  # pragma: no cover — heavy deps
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
    except ImportError:
        return ""
    lang = "heb+eng" if is_hebrew else "eng"
    images = convert_from_bytes(raw, dpi=200)
    out = []
    for img in images:
        out.append(pytesseract.image_to_string(img, lang=lang))
    return "\n\n".join(out)
