"""Bank reconciler unit tests."""

from __future__ import annotations

from datetime import date

from app.reconcile.bank import BankLine, GLLine, reconcile_bank


def test_simple_match_by_amount_date_and_description() -> None:
    bank = [BankLine(id="b1", value_date=date(2024, 6, 1), amount=100.00, description="ACME INV 123")]
    gl = [GLLine(id="g1", je_date=date(2024, 6, 1), amount=100.00, description="Invoice 123 from ACME")]
    res = reconcile_bank(bank, gl)
    assert len(res.matched) == 1
    assert res.matched[0].bank_id == "b1"
    assert res.matched[0].gl_id == "g1"
    assert res.unmatched_bank == ()
    assert res.unmatched_gl == ()


def test_amount_mismatch_outside_tolerance_no_match() -> None:
    bank = [BankLine(id="b1", value_date=date(2024, 6, 1), amount=100.00, description="ACME")]
    gl = [GLLine(id="g1", je_date=date(2024, 6, 1), amount=101.00, description="ACME")]
    res = reconcile_bank(bank, gl, amount_tolerance=0.01)
    assert res.matched == ()
    assert res.unmatched_bank == ("b1",)
    assert res.unmatched_gl == ("g1",)


def test_description_below_threshold_no_match() -> None:
    bank = [BankLine(id="b1", value_date=date(2024, 6, 1), amount=100.0, description="ACME Corp invoice")]
    gl = [GLLine(id="g1", je_date=date(2024, 6, 1), amount=100.0, description="Totally unrelated text")]
    res = reconcile_bank(bank, gl, description_threshold=80)
    assert res.matched == ()


def test_one_to_one_matching_prevents_double_assignment() -> None:
    bank = [
        BankLine(id="b1", value_date=date(2024, 6, 1), amount=100.0, description="ACME"),
        BankLine(id="b2", value_date=date(2024, 6, 2), amount=100.0, description="ACME"),
    ]
    gl = [GLLine(id="g1", je_date=date(2024, 6, 1), amount=100.0, description="ACME")]
    res = reconcile_bank(bank, gl)
    assert len(res.matched) == 1
    # The unmatched bank line is correctly surfaced.
    assert len(res.unmatched_bank) == 1
