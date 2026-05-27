from __future__ import annotations

import sys
import types

from app.audit.workpapers import renderer


def test_pdf_output_to_bytes_accepts_legacy_fpdf_string() -> None:
    raw = "%PDF-1.3\n%\xe2\xe3\xcf\xd3\n"

    assert renderer._pdf_output_to_bytes(raw) == raw.encode("latin-1")


def test_render_pdf_bytes_falls_back_when_weasyprint_render_fails(monkeypatch) -> None:
    class BrokenHTML:
        def __init__(self, string: str) -> None:
            self.string = string

        def write_pdf(self) -> bytes:
            raise ValueError("native renderer failed")

    fake_weasyprint = types.SimpleNamespace(HTML=BrokenHTML)
    monkeypatch.setitem(sys.modules, "weasyprint", fake_weasyprint)

    pdf = renderer.render_pdf_bytes("# Memo\n\nBody")

    assert pdf.startswith(b"%PDF")


def test_render_pdf_bytes_returns_stub_when_both_backends_fail(monkeypatch) -> None:
    """When WeasyPrint AND fpdf2 both blow up, the export endpoint must
    not 500 — we return a minimal valid PDF so the user still gets a
    downloadable file with the failure reason embedded.
    """

    class BrokenHTML:
        def __init__(self, string: str) -> None:
            self.string = string

        def write_pdf(self) -> bytes:
            raise OSError("native renderer missing")

    class BrokenFPDF:
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError("fpdf2 catastrophic init failure")

    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=BrokenHTML))
    monkeypatch.setitem(sys.modules, "fpdf", types.SimpleNamespace(FPDF=BrokenFPDF))

    pdf = renderer.render_pdf_bytes("# Memo\n\nBody")

    assert pdf.startswith(b"%PDF")
    assert b"%%EOF" in pdf


def test_render_pdf_bytes_rejects_non_pdf_weasyprint_output(monkeypatch) -> None:
    """If WeasyPrint mis-returns (None, junk bytes), fall through to fpdf2
    instead of streaming a corrupt body to the browser.
    """

    class WeirdHTML:
        def __init__(self, string: str) -> None:
            self.string = string

        def write_pdf(self) -> object:
            return None  # type: ignore[return-value]

    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=WeirdHTML))

    pdf = renderer.render_pdf_bytes("# Memo\n\nBody")

    assert pdf.startswith(b"%PDF")


def test_render_pdf_bytes_continues_after_single_bad_line(monkeypatch) -> None:
    """A single line that raises during fpdf2 rendering must not nuke the
    whole memo — the rest of the lines should still make it onto the page.

    The renderer's per-line ``_render_md_line`` call is wrapped in a
    try/except inside ``_fpdf_render``, so a single exploding line gets
    skipped while the loop keeps walking. The monkeypatched stub accepts
    ``**kwargs`` because the helper signature is intentionally a moving
    target (the document-direction context lives on the pdf instance).
    """

    real_render_md_line = renderer._render_md_line
    calls: list[str] = []

    def maybe_explode(pdf, line: str, epw: float, font_name: str, **kwargs) -> None:
        calls.append(line)
        if "EXPLODE" in line:
            raise RuntimeError("simulated bad glyph")
        real_render_md_line(pdf, line, epw, font_name, **kwargs)

    monkeypatch.setattr(renderer, "_render_md_line", maybe_explode)
    # Also force weasyprint to fail so we land on the fpdf2 path.
    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace())

    pdf = renderer.render_pdf_bytes("Good line one\nEXPLODE bad line\nGood line two")

    assert pdf.startswith(b"%PDF")
    # All three lines were attempted — the middle one failed but the loop
    # continued instead of aborting.
    assert any("Good line one" in c for c in calls)
    assert any("EXPLODE" in c for c in calls)
    assert any("Good line two" in c for c in calls)


def test_render_pdf_bytes_swallows_base_exception_from_fpdf_import(monkeypatch) -> None:
    """A BaseException-derived error from importing fpdf (e.g.
    ``pyo3_runtime.PanicException`` when cryptography's Rust bindings fail
    to load on a slim host) must still degrade to a stub PDF — never
    propagate as a bare 500 to the export endpoint. Reproduces the
    Render free-tier failure where the user saw an opaque "הייצוא נכשל
    (500)" pill with no error detail (the panic escaped every
    ``except Exception`` in the stack so the response wasn't JSON).
    """

    class FakePanic(BaseException):
        """Stand-in for pyo3_runtime.PanicException — a direct BaseException
        subclass, NOT an Exception subclass."""

    class ExplodingFPDF:
        def __init__(self, *args, **kwargs) -> None:
            raise FakePanic("simulated rust panic on import path")

    # Make weasyprint unavailable so we land on the fpdf2 path, then make
    # FPDF() itself raise a BaseException-derived error inside _fpdf_render.
    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "fpdf", types.SimpleNamespace(FPDF=ExplodingFPDF))

    pdf = renderer.render_pdf_bytes("# Memo\n\nBody")

    assert pdf.startswith(b"%PDF")
    assert b"PDF rendering failed" in pdf


def test_render_pdf_bytes_still_propagates_system_exit(monkeypatch) -> None:
    """Don't swallow process-control signals — SystemExit / KeyboardInterrupt
    must propagate so uvicorn / pytest can shut down cleanly. Only "rescue"
    BaseExceptions that represent runtime / library failures.
    """

    class ExitingFPDF:
        def __init__(self, *args, **kwargs) -> None:
            raise SystemExit("graceful shutdown")

    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "fpdf", types.SimpleNamespace(FPDF=ExitingFPDF))

    try:
        renderer.render_pdf_bytes("# Memo\n\nBody")
    except SystemExit:
        return
    raise AssertionError("SystemExit must propagate, not get swallowed into a stub PDF")


def test_stub_pdf_is_parseable_and_carries_message() -> None:
    """The hand-built stub must be a structurally valid PDF that contains
    the failure message (so the user sees *why* the export degraded).
    """
    pdf = renderer._stub_pdf("PDF rendering failed: deliberate")

    assert pdf.startswith(b"%PDF")
    assert b"%%EOF" in pdf
    assert b"PDF rendering failed: deliberate" in pdf
