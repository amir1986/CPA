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
    """Render PDF from markdown via WeasyPrint when available, else raise."""
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("WeasyPrint not installed") from exc
    # Trivial markdown → HTML; nothing fancy. The plan defers a real
    # markdown renderer to Phase 8.
    html = "<html><body><pre style='font-family: sans-serif;'>" + _escape(body_md) + "</pre></body></html>"
    return HTML(string=html).write_pdf()


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
