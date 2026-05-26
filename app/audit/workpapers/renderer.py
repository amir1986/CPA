"""Markdown-only workpaper renderer.

Uses str.Template-style substitution rather than Jinja2 to keep dependencies
minimal and the rendering deterministic. PDF generation hooks in via
WeasyPrint in the audit endpoint when ``CPA_PDF_BACKEND=weasyprint``.

Templates live in ``config/workpaper_templates/*.md.tmpl``. Each template is
top-and-tailed with a DRAFT — REQUIRES REVIEW banner so generated files
can't be mistaken for signed-off work product.
"""

from __future__ import annotations

import logging
import re
import string
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DRAFT_BANNER = "> **DRAFT — REQUIRES PARTNER REVIEW**\n"


@dataclass(frozen=True)
class RenderedWorkpaper:
    title: str
    body_md: str
    references: dict[str, object]


def render_template(
    template_name: str,
    *,
    inputs: dict[str, object],
    references: dict[str, object] | None = None,
    templates_dir: Path | None = None,
) -> RenderedWorkpaper:
    templates_dir = templates_dir or Path(__file__).resolve().parents[2].parent / "config" / "workpaper_templates"
    path = templates_dir / f"{template_name}.md.tmpl"
    if not path.exists():
        raise FileNotFoundError(f"workpaper template not found: {template_name} (at {path})")
    raw = path.read_text(encoding="utf-8")
    # Render with safe_substitute so missing keys become empty.
    rendered_body = string.Template(raw).safe_substitute({k: str(v) for k, v in inputs.items()})
    title = str(inputs.get("title", template_name))
    body = f"{DRAFT_BANNER}\n{rendered_body}"
    return RenderedWorkpaper(title=title, body_md=body, references=references or {})


def render_pdf_bytes(body_md: str) -> bytes:
    """Render a memo PDF from markdown.

    Tries WeasyPrint first (best HTML/CSS output, supports CSS @page).
    Falls back to fpdf2 (pure-Python, ~500 KB install, no system libs) so
    the export works on every deploy regardless of whether WeasyPrint
    could be built. fpdf2 uses a system Unicode TTF when one is found so
    Hebrew (and any other non-Latin script in the memo) renders correctly.

    Last-resort fallback: if BOTH backends fail (unsupported glyph,
    corrupted state, missing fonts on a stripped runtime), we still
    return a minimal-but-valid PDF with the error embedded so the export
    endpoint never has to surface a 500 — the user gets a downloadable
    file that clearly shows what went wrong.
    """
    # Path 1 — WeasyPrint (preferred when available). Catches BOTH ImportError
    # (package not installed) and OSError (package installed but native libs
    # libcairo/libpango missing) so the fpdf2 fallback always runs instead of
    # crashing the export with an opaque 500.
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]

        html = (
            "<html><body><pre style='font-family: sans-serif; white-space: pre-wrap;'>"
            + _escape(body_md)
            + "</pre></body></html>"
        )
        result = HTML(string=html).write_pdf()
        if isinstance(result, (bytes, bytearray)) and bytes(result[:4]) == b"%PDF":
            return bytes(result)
        logger.warning(
            "WeasyPrint returned non-PDF output (%s); falling back to fpdf2",
            type(result).__name__,
        )
    except Exception as exc:
        logger.warning("WeasyPrint PDF render unavailable; falling back to fpdf2: %r", exc)

    # Path 2 — fpdf2 fallback. Always available in core deps now.
    try:
        from fpdf import FPDF  # type: ignore[import-untyped]

        return _fpdf_render(body_md, FPDF)
    except Exception as exc:
        logger.exception("fpdf2 render failed; emitting stub PDF instead")
        return _stub_pdf(f"PDF rendering failed: {exc!r}")


_STUB_PDF_TEMPLATE = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
    b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
    b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
)


def _stub_pdf(message: str) -> bytes:
    """Hand-build a tiny valid PDF carrying one line of ASCII text.

    Used only when both WeasyPrint and fpdf2 fail catastrophically — the
    goal is "the user got a file" rather than "the export 500'd". The
    PDF parser is permissive enough that this minimal byte sequence
    renders in every viewer we've checked (Chrome, Preview, Adobe).
    """
    # Sanitize the message so it can't break the stream syntax — strip
    # parens, backslashes, and any non-ASCII so we don't need a font
    # subset to render it.
    safe = "".join(
        c if 32 <= ord(c) < 127 and c not in "()\\" else " " for c in message
    )
    safe = safe[:500] or "PDF rendering failed."
    stream_text = f"BT /F1 12 Tf 50 740 Td ({safe}) Tj ET"
    stream_bytes = stream_text.encode("ascii", "replace")
    stream_obj = (
        f"5 0 obj<</Length {len(stream_bytes)}>>stream\n".encode("ascii")
        + stream_bytes
        + b"\nendstream\nendobj\n"
    )

    body = _STUB_PDF_TEMPLATE + stream_obj
    # Compute xref offsets relative to start of file.
    objs = [b"1 0 obj", b"2 0 obj", b"3 0 obj", b"4 0 obj", b"5 0 obj"]
    offsets: list[int] = []
    for marker in objs:
        offsets.append(body.find(marker))
    xref_offset = len(body)
    xref = b"xref\n0 6\n0000000000 65535 f \n" + b"".join(
        f"{o:010d} 00000 n \n".encode("ascii") for o in offsets
    )
    trailer = (
        b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    return body + xref + trailer


def _fpdf_render(body_md: str, FPDF: type) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Load a Unicode-capable TTF (bundled DejaVu Sans first, then system
    # fallbacks). For real Hebrew/CJK rendering ALL FOUR style faces
    # (Regular, Bold, Italic, Bold-Italic) must be registered under the
    # same family name — otherwise pdf.set_font("uni", style="I") raises
    # `Undefined font: uniI`. If a particular style's TTF isn't available
    # we register the closest fallback (Regular for Italic, Bold for
    # Bold-Italic) so the render never crashes; visual italic differen-
    # tiation is lost in that case but the text + glyphs are intact.
    font_name = "Helvetica"
    regular_path = _find_unicode_font(style="")
    bold_path = _find_unicode_font(style="B")
    italic_path = _find_unicode_font(style="I")
    bold_italic_path = _find_unicode_font(style="BI")
    if regular_path is not None:
        try:
            _add_font(pdf, "uni", "", regular_path)
            _add_font(pdf, "uni", "B", bold_path or regular_path)
            _add_font(pdf, "uni", "I", italic_path or regular_path)
            _add_font(pdf, "uni", "BI", bold_italic_path or bold_path or regular_path)
            font_name = "uni"
        except Exception as exc:
            logger.warning(
                "fpdf2 add_font(%s) failed: %r — falling back to Helvetica "
                "(non-Latin glyphs will render as substitution chars)",
                regular_path, exc,
            )

    pdf.set_font(font_name, size=10)
    epw = pdf.w - pdf.l_margin - pdf.r_margin
    for raw_line in body_md.split("\n"):
        line = raw_line.rstrip()
        if not line:
            pdf.ln(3)
            continue
        try:
            _render_md_line(pdf, line, epw, font_name)
        except Exception as exc:
            # A single weird line (unsupported glyph, broken markdown, bidi
            # surprise) shouldn't blow up the whole memo — skip it and keep
            # rendering. The chunked fallback inside `_emit` already covers
            # most cases; this catches the rest (e.g. `pdf.set_font` raising
            # because a font style wasn't registered on this fpdf2 version).
            logger.warning("renderer: skipping line that raised %r: %r", exc, line[:80])
            # Reset cursor to a clean state and pretend the line was blank.
            try:
                pdf.set_x(pdf.l_margin)
                pdf.set_font(font_name, style="", size=10)
            except Exception:
                pass
    out = pdf.output()
    return _pdf_output_to_bytes(out)


def _pdf_output_to_bytes(out: object) -> bytes:
    """Normalize PDF backend output across fpdf/fpdf2 versions.

    fpdf2 returns bytes-like data. The legacy ``fpdf`` package shares the
    same import namespace and can return a latin-1 ``str`` instead; passing
    that to ``bytes(...)`` raises ``TypeError`` and turns an otherwise valid
    export into a 500.
    """
    if isinstance(out, bytes):
        return out
    if isinstance(out, bytearray):
        return bytes(out)
    if isinstance(out, str):
        return out.encode("latin-1")
    raise TypeError(f"unexpected PDF output type: {type(out).__name__}")


def _add_font(pdf, family: str, style: str, path: Path) -> None:
    """Register a TTF under the given family/style, tolerant of fpdf2 version
    differences (the legacy `uni=True` kwarg was dropped in fpdf2 >= 2.8)."""
    try:
        pdf.add_font(family, style, str(path), uni=True)
    except TypeError:
        pdf.add_font(family, style, str(path))


# Any character in these Unicode ranges flips the line to RTL rendering.
# We use the bidi algorithm for visual reordering when present.
_HEBREW_RE = re.compile(r"[֐-׿יִ-ﭏ؀-ۿݐ-ݿ]")


def _is_rtl_line(line: str) -> bool:
    return bool(_HEBREW_RE.search(line))


def _to_display(line: str) -> str:
    """Apply the bidi algorithm so a Hebrew logical-order string ('שלום') is
    re-ordered into visual order for left-to-right glyph emission, which is
    what PDF text drawing actually does. Falls back to the original string
    if python-bidi isn't installed."""
    try:
        from bidi.algorithm import get_display  # type: ignore[import-untyped]
        return get_display(line)
    except ImportError:
        return line
    except Exception as exc:
        logger.warning("bidi.get_display failed: %r — rendering logical-order", exc)
        return line


def _render_md_line(pdf, line: str, epw: float, font_name: str) -> None:
    """Render one markdown-aware line.

    Recognized markdown:
      - '# / ## / ###' headings → larger font + bold
      - '> ' blockquote → italic, indented
      - '**text**' inline bold → fpdf2's markdown=True
      - '_text_' inline italic → fpdf2's markdown=True
      - '---' rule → horizontal line
      - bullets ('- ', '* ') stay as-is (markdown=True handles them poorly).

    Hebrew/RTL lines are bidi-reordered and right-aligned.
    """
    rtl = _is_rtl_line(line)
    align = "R" if rtl else "L"

    # Horizontal rule
    if line.strip() in ("---", "***", "___"):
        pdf.set_x(pdf.l_margin)
        y = pdf.get_y() + 1
        pdf.line(pdf.l_margin, y, pdf.l_margin + epw, y)
        pdf.ln(3)
        return

    # Headings — set size + bold, then revert
    head_match = re.match(r"^(#{1,6})\s+(.*)$", line)
    if head_match:
        depth = len(head_match.group(1))
        text = head_match.group(2).strip()
        # Sizes: # 16, ## 13, ### 11, #### 10
        sizes = {1: 16, 2: 13, 3: 11}
        size = sizes.get(depth, 10)
        original_size = pdf.font_size_pt
        pdf.set_font(font_name, style="B", size=size)
        _emit(pdf, _to_display(text) if rtl else text, epw, align=align, markdown=False)
        pdf.set_font(font_name, style="", size=original_size)
        pdf.ln(1)
        return

    # Blockquote
    if line.startswith("> "):
        text = line[2:]
        pdf.set_font(font_name, style="I", size=pdf.font_size_pt)
        _emit(pdf, _to_display(text) if rtl else text, epw, align=align, markdown=True)
        pdf.set_font(font_name, style="", size=pdf.font_size_pt)
        return

    # Default body line. markdown=True parses **bold** + __italic__ inline,
    # but it doesn't play nice with Hebrew/bidi'd text — skip it for RTL.
    text = _to_display(line) if rtl else line
    _emit(pdf, text, epw, align=align, markdown=not rtl)


def _emit(pdf, text: str, epw: float, *, align: str, markdown: bool) -> None:
    """multi_cell wrapper with the same resumable-chunk safety net as the
    earlier version: no character is ever dropped silently or duplicated.

    Hebrew/RTL lines pass align='R' so the visually-reordered glyphs land
    on the right side of the page, matching reader expectation.
    """
    pdf.set_x(pdf.l_margin)
    try:
        pdf.multi_cell(epw, 5, text, align=align, markdown=markdown,
                       new_x="LMARGIN", new_y="NEXT")
        return
    except Exception:
        pdf.set_x(pdf.l_margin)

    # Resumable chunked walk — every chunk is rendered independently so a
    # partial failure can't duplicate already-committed text.
    CHUNK = 40
    for start in range(0, len(text), CHUNK):
        chunk = text[start : start + CHUNK]
        try:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(epw, 5, chunk, align=align, markdown=False,
                           new_x="LMARGIN", new_y="NEXT")
        except Exception:
            try:
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(
                    epw, 5,
                    chunk.encode("latin-1", "replace").decode("latin-1"),
                    align=align,
                    markdown=False,
                    new_x="LMARGIN",
                    new_y="NEXT",
                )
            except Exception as exc:
                logger.error("fpdf2 chunk render failed: %r", exc)


_FONT_FILES = {
    "": "DejaVuSans.ttf",
    "B": "DejaVuSans-Bold.ttf",
    "I": "DejaVuSans-Oblique.ttf",
    "BI": "DejaVuSans-BoldOblique.ttf",
}

_SYSTEM_PATHS = {
    "": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/google-noto/NotoSans-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ),
    "B": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ),
    "I": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Oblique.ttf",
    ),
    "BI": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-BoldOblique.ttf",
    ),
}


def _find_unicode_font(*, style: str = "") -> Path | None:
    """Search for a Unicode-capable TrueType font for the requested style
    ('', 'B', 'I', 'BI'). Returns None if not found — caller decides whether
    to fall back to a different style's TTF."""
    fname = _FONT_FILES.get(style, _FONT_FILES[""])
    bundled = Path(__file__).resolve().parent / "fonts" / fname
    if bundled.exists():
        return bundled
    for path in _SYSTEM_PATHS.get(style, ()):
        p = Path(path)
        if p.exists():
            return p
    return None


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
