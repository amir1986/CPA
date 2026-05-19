"""Excel TB/GL extractor tests — build a workbook in memory, then parse."""

from __future__ import annotations

import io

import pytest

openpyxl = pytest.importorskip("openpyxl")

from app.ingest_docs.extractors.excel import extract_gl, extract_trial_balance


def _build_workbook(rows: list[list]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_trial_balance_round_trip() -> None:
    xlsx = _build_workbook([
        ["Engagement", "ACME Audit"],
        [],
        ["Code", "Account Name", "Opening", "Debit", "Credit", "Closing"],
        ["1000", "Cash", 1000, 500, 200, 1300],
        ["2000", "AP", 0, 100, 800, -700],
    ])
    rows = extract_trial_balance(xlsx)
    assert len(rows) == 2
    assert rows[0].account_code == "1000"
    assert rows[0].closing == 1300
    assert rows[1].account_name == "AP"


def test_gl_round_trip_with_separate_debit_credit() -> None:
    xlsx = _build_workbook([
        ["JE No", "Date", "Account", "Description", "Debit", "Credit", "Preparer"],
        ["JE-001", "2024-06-01", "1000", "Cash receipt", 5000, 0, "alice"],
        ["JE-001", "2024-06-01", "4000", "Sale", 0, 5000, "alice"],
    ])
    rows = extract_gl(xlsx)
    assert len(rows) == 2
    assert rows[0].account_code == "1000"
    assert rows[0].debit == 5000
    assert rows[1].credit == 5000
    assert rows[0].preparer == "alice"


def test_gl_signed_amount_column_distributes_debit_credit() -> None:
    xlsx = _build_workbook([
        ["JE No", "Date", "Account", "Memo", "Amount"],
        ["JE-009", "2024-06-15", "5000", "COGS", 1234.56],
        ["JE-009", "2024-06-15", "1000", "Cash out", -1234.56],
    ])
    rows = extract_gl(xlsx)
    assert len(rows) == 2
    assert rows[0].debit == pytest.approx(1234.56)
    assert rows[0].credit == 0.0
    assert rows[1].debit == 0.0
    assert rows[1].credit == pytest.approx(1234.56)


def test_extractor_returns_empty_when_no_header_found() -> None:
    xlsx = _build_workbook([["junk", "junk"], [1, 2]])
    assert extract_trial_balance(xlsx) == []
    assert extract_gl(xlsx) == []
