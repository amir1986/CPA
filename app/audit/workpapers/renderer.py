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


# ─────────────── styling constants ───────────────
#
# Sizes / colors live as module constants so the WeasyPrint and fpdf2 paths
# can stay in visual sync.

# Brand-ish slate that prints well at any zoom.
_C_INK = (24, 28, 36)          # body text
_C_MUTED = (96, 104, 118)      # secondary labels
_C_ACCENT = (35, 96, 178)      # headings + rule
_C_DRAFT_BG = (252, 234, 196)  # soft amber for the DRAFT banner
_C_DRAFT_FG = (124, 73, 0)
_C_QUOTE_BG = (244, 246, 250)  # callout background for verbatim quotes
_C_QUOTE_BAR = (175, 188, 207)
_C_RULE = (210, 216, 225)

# Per-heading font size (pt).
_H_SIZES = {1: 18, 2: 13, 3: 11, 4: 10}
# Space (mm) above / below each heading level.
_H_SPACE_BEFORE = {1: 0, 2: 4, 3: 3, 4: 2}
_H_SPACE_AFTER = {1: 3, 2: 2, 3: 1, 4: 1}

_BODY_SIZE = 10.5
_LINE_HEIGHT = 5.6           # mm per body line — looser than fpdf2's default
_HEADING_LINE_HEIGHT = 7.0


def render_pdf_bytes(body_md: str, *, locale: str = "en") -> bytes:
    """Render a memo PDF from markdown.

    Tries WeasyPrint first (best HTML/CSS output, supports CSS @page).
    Falls back to fpdf2 (pure-Python, ~500 KB install, no system libs) so
    the export works on every deploy regardless of whether WeasyPrint
    could be built. fpdf2 uses a system Unicode TTF when one is found so
    Hebrew (and any other non-Latin script in the memo) renders correctly.

    ``locale`` selects document direction + UI strings used in chrome
    (header / footer / page label). The body markdown is rendered as-is —
    callers translate prose BEFORE calling this. Verbatim quotes inside
    the markdown are never altered.

    Last-resort fallback: if BOTH backends fail (unsupported glyph,
    corrupted state, missing fonts on a stripped runtime), we still
    return a minimal-but-valid PDF with the error embedded so the export
    endpoint never has to surface a 500 — the user gets a downloadable
    file that clearly shows what went wrong.
    """
    is_he = locale == "he"
    # Path 1 — WeasyPrint (preferred when available). Catches BOTH ImportError
    # (package not installed) and OSError (package installed but native libs
    # libcairo/libpango missing) so the fpdf2 fallback always runs instead of
    # crashing the export with an opaque 500. Also catches BaseException-
    # derived runtime panics (pyo3_runtime.PanicException raised when
    # cryptography's Rust bindings fail to load — observed on Render's
    # free-tier slim install) which would otherwise propagate past `Exception`
    # and surface as a bare 500 with no JSON body the UI can parse.
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]

        html = _build_weasy_html(body_md, is_he=is_he)
        result = HTML(string=html).write_pdf()
        # Belt-and-suspenders: if WeasyPrint mis-returns (None, a non-PDF
        # bytes blob from a misconfigured renderer) we'd otherwise stream
        # garbage to the browser. Validate the magic bytes before trusting it.
        if isinstance(result, (bytes, bytearray)) and bytes(result[:4]) == b"%PDF":
            return bytes(result)
        logger.warning(
            "WeasyPrint returned non-PDF output (%s); falling back to fpdf2",
            type(result).__name__,
        )
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except BaseException as exc:
        logger.warning("WeasyPrint PDF render unavailable; falling back to fpdf2: %r", exc)

    # Path 2 — fpdf2 fallback. Always available in core deps now.
    try:
        from fpdf import FPDF  # type: ignore[import-untyped]

        return _fpdf_render(body_md, FPDF, is_he=is_he)
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        # Process-level signals — propagate so cleanup / shutdown still works.
        raise
    except BaseException as exc:
        # Path 3 — both backends failed. Emit a minimal valid PDF carrying
        # the failure reason so the user gets *something* downloadable
        # rather than a 500. This protects the export endpoint from
        # catastrophic failures we can't otherwise recover from. Catching
        # BaseException (not just Exception) is critical here: `from fpdf
        # import FPDF` transitively imports `cryptography`, whose Rust
        # bindings can raise `pyo3_runtime.PanicException` (a direct
        # BaseException subclass) when `_cffi_backend` or the native
        # openssl module is unavailable on the host — that path would
        # otherwise escape every `except Exception` clause in the stack.
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


# ─────────────── WeasyPrint HTML path ───────────────


def _build_weasy_html(body_md: str, *, is_he: bool) -> str:
    """Construct a styled HTML document from the memo markdown.

    Only used when WeasyPrint is available; on Render this is not the
    default path (no libcairo/libpango). The fpdf2 fallback below is the
    one we actually ship — but keeping this in sync means a properly
    configured deploy gets a much nicer-looking memo.
    """
    direction = "rtl" if is_he else "ltr"
    body_class = "rtl" if is_he else "ltr"
    css = """
@page { size: A4; margin: 22mm 20mm 22mm 20mm; }
body { font-family: 'DejaVu Sans', 'Noto Sans', 'Arial Unicode MS', sans-serif;
       font-size: 10.5pt; color: #181c24; line-height: 1.55; }
body.rtl { direction: rtl; text-align: right; }
body.ltr { direction: ltr; text-align: left; }
h1 { font-size: 18pt; color: #2360b2; margin: 0 0 6mm; font-weight: 700; }
h2 { font-size: 13pt; color: #2360b2; margin: 6mm 0 2mm; border-bottom: 1px solid #d2d8e1; padding-bottom: 1mm; }
h3 { font-size: 11pt; color: #181c24; margin: 4mm 0 1mm; font-weight: 600; }
h4 { font-size: 10pt; color: #606276; margin: 3mm 0 1mm; text-transform: uppercase; letter-spacing: .04em; }
blockquote { background: #f4f6fa; border-inline-start: 3px solid #afbccf;
             padding: 2mm 3mm; margin: 1.5mm 0; border-radius: 1mm; }
blockquote.draft { background: #fceac4; color: #7c4900; border-inline-start: 3px solid #c08a2c;
                   font-weight: 600; }
em, i { font-style: italic; }
strong, b { font-weight: 700; }
.muted { color: #606276; }
hr { border: 0; border-top: 1px solid #d2d8e1; margin: 4mm 0; }
"""
    body_html = _markdown_to_html(body_md)
    return (
        f"<!doctype html><html lang=\"{'he' if is_he else 'en'}\" dir=\"{direction}\">"
        f"<head><meta charset=\"utf-8\"><style>{css}</style></head>"
        f"<body class=\"{body_class}\">{body_html}</body></html>"
    )


def _markdown_to_html(body_md: str) -> str:
    """Minimal markdown→HTML conversion sufficient for the memo subset.

    Recognized:
      - # ## ### #### headings
      - > blockquote (single-line, contiguous lines fold into one block)
      - --- / *** horizontal rule
      - **bold** + _italic_ inline
      - bullets ('- ' or '* ') as <ul>
      - blank lines split paragraphs
    """
    blocks: list[str] = []
    buf: list[str] = []
    quote_buf: list[str] = []
    list_buf: list[str] = []

    def flush_paragraph() -> None:
        if buf:
            blocks.append("<p>" + "<br>".join(_inline(line) for line in buf) + "</p>")
            buf.clear()

    def flush_quote() -> None:
        if quote_buf:
            cls = ' class="draft"' if any("DRAFT" in q for q in quote_buf) else ""
            blocks.append(
                f"<blockquote{cls}>"
                + "<br>".join(_inline(q) for q in quote_buf)
                + "</blockquote>"
            )
            quote_buf.clear()

    def flush_list() -> None:
        if list_buf:
            blocks.append("<ul>" + "".join(f"<li>{_inline(it)}</li>" for it in list_buf) + "</ul>")
            list_buf.clear()

    for raw in body_md.split("\n"):
        line = raw.rstrip()
        if not line:
            flush_paragraph()
            flush_quote()
            flush_list()
            continue
        if line.strip() in ("---", "***", "___"):
            flush_paragraph()
            flush_quote()
            flush_list()
            blocks.append("<hr>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush_paragraph()
            flush_quote()
            flush_list()
            depth = min(len(m.group(1)), 4)
            blocks.append(f"<h{depth}>{_inline(m.group(2).strip())}</h{depth}>")
            continue
        if line.startswith("> "):
            flush_paragraph()
            flush_list()
            quote_buf.append(line[2:])
            continue
        if line.lstrip().startswith(("- ", "* ")):
            flush_paragraph()
            flush_quote()
            list_buf.append(line.lstrip()[2:])
            continue
        flush_quote()
        flush_list()
        buf.append(line)

    flush_paragraph()
    flush_quote()
    flush_list()
    return "\n".join(blocks)


def _inline(text: str) -> str:
    s = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"<em>\1</em>", s)
    return s


# ─────────────── fpdf2 fallback path ───────────────


def _fpdf_render(body_md: str, FPDF: type, *, is_he: bool) -> bytes:
    # Build the PDF + register fonts BEFORE the first add_page() so the
    # auto-fired header() override never reaches for a glyph the font
    # can't draw (the en em-dash and Hebrew chrome strings live in the
    # header — Helvetica's latin-1 chokes on both).
    pdf = _build_pdf(FPDF, is_he=is_he)
    font_name = _register_fonts(pdf)
    pdf.add_page()

    pdf.set_font(font_name, size=_BODY_SIZE)
    pdf.set_text_color(*_C_INK)
    epw = pdf.w - pdf.l_margin - pdf.r_margin
    default_align = "R" if is_he else "L"
    # Stash on the pdf instance so monkeypatched test versions of
    # ``_render_md_line`` (which take only the 4-arg signature) still get
    # the right document-level default without us needing to thread these
    # through as kwargs at every call site.
    pdf._cpa_default_align = default_align  # type: ignore[attr-defined]
    pdf._cpa_in_quote_block = False  # type: ignore[attr-defined]

    for raw_line in body_md.split("\n"):
        line = raw_line.rstrip()
        if not line:
            pdf.ln(2.5)
            pdf._cpa_in_quote_block = False  # type: ignore[attr-defined]
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
            try:
                pdf.set_x(pdf.l_margin)
                pdf.set_font(font_name, style="", size=_BODY_SIZE)
                pdf.set_text_color(*_C_INK)
            except Exception:
                pass
        # Track quote-block grouping for tightened spacing on consecutive
        # blockquote lines. Stored on the pdf instance (see above).
        pdf._cpa_in_quote_block = line.startswith("> ")  # type: ignore[attr-defined]
    out = pdf.output()
    return _pdf_output_to_bytes(out)


def _build_pdf(FPDF: type, *, is_he: bool):
    """Construct an FPDF instance with the page header/footer chrome.

    fpdf2 calls ``header()`` and ``footer()`` automatically on every page.
    We override them so each memo page carries the title bar and a
    centred ``Page X / Y`` indicator — the latter uses fpdf2's
    ``{nb}`` total-pages token.
    """
    label_page = "עמוד" if is_he else "Page"
    label_of = "מתוך" if is_he else "of"
    draft_text = "טיוטה — דורש סקירת שותף" if is_he else "DRAFT — Requires partner review"

    class StyledPDF(FPDF):  # type: ignore[misc]
        font_name = "Helvetica"

        def header(self) -> None:
            # Light grey rule across the top of every page.
            self.set_draw_color(*_C_RULE)
            self.set_line_width(0.2)
            self.line(self.l_margin, 12, self.w - self.r_margin, 12)
            # Tiny DRAFT chip — same colour on every page so it never feels
            # like a signed deliverable.
            self.set_xy(self.l_margin, 6)
            self.set_font(self.font_name, style="B", size=8)
            self.set_text_color(*_C_DRAFT_FG)
            self.cell(
                self.w - self.l_margin - self.r_margin, 4,
                draft_text,
                align="R" if is_he else "L",
                new_x="LMARGIN", new_y="NEXT",
            )
            # Reset to body defaults so caller code never has to.
            self.set_text_color(*_C_INK)
            self.set_font(self.font_name, style="", size=_BODY_SIZE)
            self.set_xy(self.l_margin, 18)

        def footer(self) -> None:
            self.set_y(-12)
            self.set_font(self.font_name, style="", size=8)
            self.set_text_color(*_C_MUTED)
            txt = f"{label_page} {self.page_no()} {label_of} {{nb}}"
            self.cell(
                self.w - self.l_margin - self.r_margin, 4, txt,
                align="C", new_x="LMARGIN", new_y="NEXT",
            )
            self.set_text_color(*_C_INK)

    pdf = StyledPDF(format="A4")
    pdf.set_margins(left=20, top=22, right=20)
    pdf.set_auto_page_break(auto=True, margin=22)
    # Enable the {nb} total-pages alias so the footer can render "Page 2 of 5".
    pdf.alias_nb_pages()
    return pdf


def _register_fonts(pdf) -> str:
    """Register a Unicode-capable TTF and return the family name to use.

    For real Hebrew/CJK rendering ALL FOUR style faces (Regular, Bold,
    Italic, Bold-Italic) must be registered under the same family name —
    otherwise ``pdf.set_font("uni", style="I")`` raises
    ``Undefined font: uniI``. If a particular style's TTF isn't available
    we register the closest fallback (Regular for Italic, Bold for
    Bold-Italic) so the render never crashes; visual italic differentia-
    tion is lost in that case but the text + glyphs are intact.
    """
    regular_path = _find_unicode_font(style="")
    bold_path = _find_unicode_font(style="B")
    italic_path = _find_unicode_font(style="I")
    bold_italic_path = _find_unicode_font(style="BI")
    if regular_path is None:
        return "Helvetica"
    try:
        _add_font(pdf, "uni", "", regular_path)
        _add_font(pdf, "uni", "B", bold_path or regular_path)
        _add_font(pdf, "uni", "I", italic_path or regular_path)
        _add_font(pdf, "uni", "BI", bold_italic_path or bold_path or regular_path)
        # Tell the header/footer overrides which font to use for the chrome.
        pdf.font_name = "uni"  # type: ignore[attr-defined]
        return "uni"
    except Exception as exc:
        logger.warning(
            "fpdf2 add_font(%s) failed: %r — falling back to Helvetica "
            "(non-Latin glyphs will render as substitution chars)",
            regular_path, exc,
        )
        return "Helvetica"


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
_HEBREW_RE = re.compile(r"[֐-׿יִ-ﭏ؀-ۿݐ-ݿ]")


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
      - '# / ## / ###' headings → larger font + bold accent colour
      - '> ' blockquote → padded callout block with a vertical accent bar
      - '**text**' inline bold → fpdf2's markdown=True
      - '_text_' inline italic → fpdf2's markdown=True
      - '---' rule → horizontal line
      - bullets ('- ', '* ') stay as-is.

    The 4-arg signature is kept stable so callers (and the unit-test
    monkeypatch) can replace this helper without juggling kwargs. The
    document's flow direction and quote-grouping state come off the
    ``pdf`` instance via the ``_cpa_*`` attributes set by ``_fpdf_render``.
    """
    default_align = getattr(pdf, "_cpa_default_align", "L")
    in_quote_block = getattr(pdf, "_cpa_in_quote_block", False)

    rtl = _is_rtl_line(line)
    # Lines without any Hebrew fall back to the document's default flow
    # direction, so a Hebrew memo doesn't end up looking like a mix of
    # right- and left-aligned paragraphs.
    align = "R" if rtl else default_align

    # Horizontal rule.
    if line.strip() in ("---", "***", "___"):
        pdf.set_draw_color(*_C_RULE)
        pdf.set_line_width(0.3)
        y = pdf.get_y() + 2
        pdf.line(pdf.l_margin, y, pdf.l_margin + epw, y)
        pdf.ln(5)
        return

    # Headings — set size + bold accent colour, then revert.
    head_match = re.match(r"^(#{1,6})\s+(.*)$", line)
    if head_match:
        depth = len(head_match.group(1))
        text = head_match.group(2).strip()
        size = _H_SIZES.get(depth, _BODY_SIZE)
        before = _H_SPACE_BEFORE.get(depth, 1)
        after = _H_SPACE_AFTER.get(depth, 1)
        if before:
            pdf.ln(before)
        # Top-level title + section heading get the accent colour.
        if depth <= 2:
            pdf.set_text_color(*_C_ACCENT)
        else:
            pdf.set_text_color(*_C_INK)
        pdf.set_font(font_name, style="B", size=size)
        _emit(
            pdf,
            _to_display(text) if rtl else text,
            epw,
            align=align,
            markdown=False,
            line_height=_HEADING_LINE_HEIGHT,
        )
        # Subtle underline rule under H2s so section breaks read clearly.
        if depth == 2:
            pdf.set_draw_color(*_C_RULE)
            pdf.set_line_width(0.2)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.l_margin + epw, y)
            pdf.ln(0.5)
        pdf.set_text_color(*_C_INK)
        pdf.set_font(font_name, style="", size=_BODY_SIZE)
        if after:
            pdf.ln(after)
        return

    # Blockquote — render as a soft-grey callout with a coloured side bar.
    if line.startswith("> "):
        text = line[2:]
        is_draft = "DRAFT" in text or "טיוטה" in text
        bg = _C_DRAFT_BG if is_draft else _C_QUOTE_BG
        bar = _C_DRAFT_FG if is_draft else _C_QUOTE_BAR
        fg = _C_DRAFT_FG if is_draft else _C_INK
        _emit_quote_line(
            pdf,
            text,
            epw,
            font_name,
            align=align,
            rtl=rtl,
            bg=bg,
            bar=bar,
            fg=fg,
            is_draft=is_draft,
            in_quote_block=in_quote_block,
        )
        return

    # Default body line. markdown=True parses **bold** + _italic_ inline,
    # but it doesn't play nice with Hebrew/bidi'd text — skip it for RTL.
    text = _to_display(line) if rtl else line
    _emit(pdf, text, epw, align=align, markdown=not rtl, line_height=_LINE_HEIGHT)


def _emit_quote_line(
    pdf,
    text: str,
    epw: float,
    font_name: str,
    *,
    align: str,
    rtl: bool,
    bg: tuple[int, int, int],
    bar: tuple[int, int, int],
    fg: tuple[int, int, int],
    is_draft: bool,
    in_quote_block: bool,
) -> None:
    """Render a > line as a callout — soft background, accent bar on the
    leading edge, italic body text. Uses fpdf2's ``fill`` + side ``border``
    so the painted region exactly matches the wrapped text height (no
    approximations, no 1px seams between consecutive quote lines)."""
    if not in_quote_block:
        pdf.ln(1)

    pdf.set_font(font_name, style="BI" if is_draft else "I", size=_BODY_SIZE)
    display = _to_display(text) if rtl else text
    line_h = _LINE_HEIGHT + 0.6

    # The side border doubles as the accent bar — bump its width so it
    # reads as a coloured stripe rather than a hairline.
    pdf.set_fill_color(*bg)
    pdf.set_text_color(*fg)
    pdf.set_draw_color(*bar)
    pdf.set_line_width(1.4)
    border = "R" if rtl else "L"

    pdf.set_x(pdf.l_margin)
    try:
        pdf.multi_cell(
            epw, line_h, display, align=align,
            markdown=not rtl and not is_draft,
            fill=True, border=border,
            new_x="LMARGIN", new_y="NEXT",
        )
    except Exception:
        # Chunked fallback — keep the render from crashing on weird glyphs
        # or extreme widths. Background fill is dropped for the fallback so
        # we never half-paint a callout.
        pdf.set_x(pdf.l_margin)
        for start in range(0, len(display), 40):
            chunk = display[start : start + 40]
            try:
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(epw, line_h, chunk, align=align, markdown=False,
                               new_x="LMARGIN", new_y="NEXT")
            except Exception:
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(
                    epw, line_h,
                    chunk.encode("latin-1", "replace").decode("latin-1"),
                    align=align, markdown=False, new_x="LMARGIN", new_y="NEXT",
                )
    pdf.set_text_color(*_C_INK)
    pdf.set_draw_color(*_C_RULE)
    pdf.set_line_width(0.2)
    pdf.set_font(font_name, style="", size=_BODY_SIZE)


def _emit(
    pdf,
    text: str,
    epw: float,
    *,
    align: str,
    markdown: bool,
    line_height: float = _LINE_HEIGHT,
) -> None:
    """multi_cell wrapper with the same resumable-chunk safety net as the
    earlier version: no character is ever dropped silently or duplicated.

    Hebrew/RTL lines pass align='R' so the visually-reordered glyphs land
    on the right side of the page, matching reader expectation.
    """
    pdf.set_x(pdf.l_margin)
    try:
        pdf.multi_cell(epw, line_height, text, align=align, markdown=markdown,
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
            pdf.multi_cell(epw, line_height, chunk, align=align, markdown=False,
                           new_x="LMARGIN", new_y="NEXT")
        except Exception:
            try:
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(
                    epw, line_height,
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
