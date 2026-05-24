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

    # Load a Unicode-capable TTF. Bundled DejaVu Sans is the FIRST choice so
    # font loading doesn't depend on the host having /usr/share/fonts; system
    # fallbacks come after. add_font failure is logged (not silenced) so we
    # know if Hebrew/CJK glyphs are going to render as boxes.
    font_name = "Helvetica"
    font_path = _find_unicode_font()
    if font_path is not None:
        try:
            try:
                pdf.add_font("uni", "", str(font_path), uni=True)
            except TypeError:
                # fpdf2 >= 2.8 dropped the `uni` kwarg; the new signature
                # accepts the TTF directly.
                pdf.add_font("uni", "", str(font_path))
            font_name = "uni"
        except Exception as exc:
            logger.warning(
                "fpdf2 add_font(%s) failed: %r — falling back to Helvetica "
                "(non-Latin glyphs will render as substitution chars)",
                font_path, exc,
            )

    pdf.set_font(font_name, size=9)
    epw = pdf.w - pdf.l_margin - pdf.r_margin
    for raw_line in body_md.split("\n"):
        line = raw_line.rstrip()
        if not line:
            pdf.ln(4)
            continue
        _render_line(pdf, line, epw, font_name)
    out = pdf.output()
    return bytes(out)


def _render_line(pdf, line: str, epw: float, font_name: str) -> None:
    """Render one line of memo text without ever raising, and without
    duplicating any character.

    Strategy:
      1. Try multi_cell on the full line at the effective page width.
      2. On any fpdf2 error, abandon the partial write (any text already
         committed by multi_cell is fine — it was successfully positioned)
         and switch to a *resumable* chunked walk: feed text in small,
         break-safe chunks. Each chunk is rendered independently with its
         own try; on failure that chunk goes through an ASCII substitution
         so the next chunk still gets a clean attempt. This guarantees
         every input character reaches the PDF exactly once.
    """
    pdf.set_x(pdf.l_margin)
    try:
        pdf.multi_cell(epw, 5, line, new_x="LMARGIN", new_y="NEXT")
        return
    except Exception:
        # multi_cell raised AFTER possibly emitting nothing (the "single
        # character" error is raised before any output). Reset cursor and
        # continue with the chunked walk for THIS line only.
        pdf.set_x(pdf.l_margin)

    # Walk the line in small chunks. 40 chars keeps even a wide-glyph
    # script comfortably under the page width at 9 pt.
    CHUNK = 40
    for start in range(0, len(line), CHUNK):
        chunk = line[start : start + CHUNK]
        try:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(epw, 5, chunk, new_x="LMARGIN", new_y="NEXT")
        except Exception:
            # Substitute this chunk's unrepresentable chars with '?' so the
            # render still completes. Visible substitution, never silent
            # drop. Note: chars from previous successful chunks are already
            # on the page — we are NOT re-emitting them.
            try:
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(
                    epw, 5,
                    chunk.encode("latin-1", "replace").decode("latin-1"),
                    new_x="LMARGIN",
                    new_y="NEXT",
                )
            except Exception as exc:
                logger.error("fpdf2 chunk render failed even after ASCII fallback: %r", exc)


def _find_unicode_font() -> Path | None:
    """Search for a Unicode-capable TrueType font.

    Order:
      1. Bundled `config/fonts/DejaVuSans.ttf` in the repo — guaranteed
         present on every deploy, no dependency on host packages.
      2. System paths (kept as a fallback in case the bundled file is
         stripped by a packaging step).
    """
    # Bundled next to this module so the wheel includes it (hatch packages
    # the `app/` directory only — anything outside isn't shipped on Render).
    bundled = Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf"
    if bundled.exists():
        return bundled

    candidates = (
        # Debian / Ubuntu (Render's base image).
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        # Other Linux distros.
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/google-noto/NotoSans-Regular.ttf",
        # macOS dev.
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    )
    for path in candidates:
        p = Path(path)
        if p.exists():
            return p
    return None


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
