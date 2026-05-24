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
        return HTML(string=html).write_pdf()
    except (ImportError, OSError):
        pass

    # Path 2 — fpdf2 fallback. Always available in core deps now.
    try:
        from fpdf import FPDF  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "No PDF backend installed (need fpdf2 or weasyprint)"
        ) from exc

    return _fpdf_render(body_md, FPDF)


def _fpdf_render(body_md: str, FPDF: type) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Load a Unicode-capable TTF (bundled DejaVu Sans first, then system
    # fallbacks). For real Hebrew/CJK rendering both Regular and Bold faces
    # are registered under the same family name so `set_font(uni, 'B')`
    # works for headings + inline **bold**.
    font_name = "Helvetica"
    font_path = _find_unicode_font()
    bold_path = _find_unicode_font(bold=True)
    if font_path is not None:
        try:
            _add_font(pdf, "uni", "", font_path)
            if bold_path is not None:
                try:
                    _add_font(pdf, "uni", "B", bold_path)
                except Exception as exc:
                    logger.warning("bold TTF load failed: %r — bold will simulate", exc)
            font_name = "uni"
        except Exception as exc:
            logger.warning(
                "fpdf2 add_font(%s) failed: %r — falling back to Helvetica "
                "(non-Latin glyphs will render as substitution chars)",
                font_path, exc,
            )

    pdf.set_font(font_name, size=10)
    epw = pdf.w - pdf.l_margin - pdf.r_margin
    for raw_line in body_md.split("\n"):
        line = raw_line.rstrip()
        if not line:
            pdf.ln(3)
            continue
        _render_md_line(pdf, line, epw, font_name)
    out = pdf.output()
    return bytes(out)


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


def _find_unicode_font(*, bold: bool = False) -> Path | None:
    """Search for a Unicode-capable TrueType font. Bundled DejaVu Sans
    (Regular + Bold) is the first choice; system paths fall back."""
    fname = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    bundled = Path(__file__).resolve().parent / "fonts" / fname
    if bundled.exists():
        return bundled

    # Fallback: search system paths.
    if bold:
        candidates = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        )
    else:
        candidates = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/google-noto/NotoSans-Regular.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
        )
    for path in candidates:
        p = Path(path)
        if p.exists():
            return p
    # If bold is missing, fall back to Regular so headings render in the
    # right script (just non-bold).
    if bold:
        return _find_unicode_font(bold=False)
    return None


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
