"""Three-way match tests."""

from __future__ import annotations

from app.audit.three_way_match import GRRecord, InvoiceRecord, PORecord, three_way_match


def test_happy_path_matches() -> None:
    pos = [PORecord("P001", "ACME", quantity=10, amount=1000)]
    grs = [GRRecord("P001", quantity_received=10)]
    inv = [InvoiceRecord("P001", "ACME", amount=1000)]
    matched, exc = three_way_match(pos, grs, inv)
    assert matched == ["P001"]
    assert exc == []


def test_quantity_mismatch_raises_exception() -> None:
    pos = [PORecord("P001", "ACME", 10, 1000)]
    grs = [GRRecord("P001", 9)]
    inv = [InvoiceRecord("P001", "ACME", 1000)]
    matched, exc = three_way_match(pos, grs, inv)
    assert matched == []
    assert exc[0].reason == "quantity mismatch"


def test_missing_gr_or_invoice_raises_exception() -> None:
    pos = [PORecord("P001", "ACME", 10, 1000), PORecord("P002", "BETA", 5, 500)]
    grs = [GRRecord("P001", 10)]
    inv = [InvoiceRecord("P002", "BETA", 500)]
    matched, exc = three_way_match(pos, grs, inv)
    assert matched == []
    reasons = sorted(e.reason for e in exc)
    assert reasons == ["missing GR", "missing invoice"]


def test_vendor_mismatch_raises_exception() -> None:
    pos = [PORecord("P001", "ACME", 10, 1000)]
    grs = [GRRecord("P001", 10)]
    inv = [InvoiceRecord("P001", "OTHER", 1000)]
    matched, exc = three_way_match(pos, grs, inv)
    assert matched == []
    assert exc[0].reason == "vendor mismatch"
