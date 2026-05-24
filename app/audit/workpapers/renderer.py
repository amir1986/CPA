"""Markdown-only workpaper renderer.

Uses str.Template-style substitution rather than Jinja2 to keep dependencies
minimal and the rendering deterministic. PDF generation hooks in via
WeasyPrint in the audit endpoint when ``CPA_PDF_BACKEND=weasyprint``.

Templates live in ``config/workpaper_templates/*.md.tmpl``. Each template is
top-and-tailed with a DRAFT — REQUIRES REVIEW banner so generated files
can't be mistaken for signed-off work product.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from pathlib import Path

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
    # Path 1 — WeasyPrint (preferred when available).
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]

        html = (
            "<html><body><pre style='font-family: sans-serif; white-space: pre-wrap;'>"
            + _escape(body_md)
            + "</pre></body></html>"
        )
        return HTML(string=html).write_pdf()
    except ImportError:
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

    # Prefer a Unicode-capable TTF so Hebrew + accented chars render. Falls
    # back to fpdf2's built-in Helvetica (Latin-only) when none is found.
    font_name = "Helvetica"
    font_path = _find_unicode_font()
    if font_path is not None:
        try:
            pdf.add_font("uni", "", str(font_path), uni=True)
            font_name = "uni"
        except Exception:
            pass

    pdf.set_font(font_name, size=10)
    # Render line-by-line. multi_cell handles wrapping at the right margin.
    for raw_line in body_md.split("\n"):
        line = raw_line.rstrip()
        if not line:
            pdf.ln(4)
            continue
        try:
            pdf.multi_cell(0, 5, line)
        except Exception:
            # Drop any character the font can't represent rather than crash
            # the whole export. Rare with DejaVu but defensive.
            pdf.multi_cell(0, 5, line.encode("latin-1", "ignore").decode("latin-1"))
    out = pdf.output()
    return bytes(out) if not isinstance(out, (bytes, bytearray)) else bytes(out)


def _find_unicode_font() -> Path | None:
    """Search common system paths for a Unicode-capable TrueType font."""
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
