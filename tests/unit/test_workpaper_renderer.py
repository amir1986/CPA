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
