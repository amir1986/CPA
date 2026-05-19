"""Tests for Benford, z-score, JE tests."""

from __future__ import annotations

from datetime import date

from app.analyze.anomalies import benford_first_digit, first_digit, z_score_outliers_by_account
from app.audit.je_tests import (
    benford_hits,
    late_posting_hits,
    round_amount_hits,
    threshold_hits,
    unusual_user_hits,
    weekend_holiday_hits,
)
from app.audit.je_tests.benford import JEAmount


def test_first_digit_extracts_correctly() -> None:
    assert first_digit(123.45) == 1
    assert first_digit(-9876.5) == 9
    assert first_digit(0.034) == 3
    assert first_digit(0.0) is None


def test_benford_uniform_amounts_are_suspect() -> None:
    # 100 amounts with first digit = 5 → wildly off Benford.
    amounts = [5000.0 + i for i in range(100)]
    r = benford_first_digit(amounts)
    assert r.n == 100
    assert r.suspect is True


def test_benford_natural_amounts_not_suspect() -> None:
    amounts = [10 ** (i / 30) for i in range(300)]  # log-distributed
    r = benford_first_digit(amounts)
    assert r.n == 300
    assert r.suspect is False


def test_z_score_outliers() -> None:
    entries = [("a", 100.0)] * 10 + [("a", 10000.0)]   # one massive outlier
    hits = z_score_outliers_by_account(entries, threshold=2.0)
    assert any(h.amount == 10000.0 for h in hits)


class _GL:
    def __init__(self, **kw): self.__dict__.update(kw)


def test_round_amount_hits() -> None:
    entries = [_GL(id="1", amount=1000.0), _GL(id="2", amount=1234.56), _GL(id="3", amount=50000.0)]
    hits = round_amount_hits(entries, units=1000)
    assert {h["entry_id"] for h in hits} == {"1", "3"}


def test_weekend_hits() -> None:
    sat = date(2024, 11, 16)  # Saturday
    mon = date(2024, 11, 18)  # Monday
    entries = [_GL(id="w", posting_date=sat, amount=10), _GL(id="m", posting_date=mon, amount=10)]
    hits = weekend_holiday_hits(entries)
    assert [h["entry_id"] for h in hits] == ["w"]


def test_unusual_user_hits_sod_violation() -> None:
    # rare_threshold=0 makes the rare-preparer rule never fire, so we
    # isolate the preparer==approver SoD-violation rule.
    entries = [
        _GL(id="ok", preparer="alice", approver="bob", amount=100),
        _GL(id="bad", preparer="carol", approver="carol", amount=200),
    ]
    hits = unusual_user_hits(entries, rare_threshold=0)
    assert len(hits) == 1
    assert hits[0]["entry_id"] == "bad"
    assert "preparer==approver" in hits[0]["reason"]


def test_unusual_user_flags_rare_preparers() -> None:
    entries = [
        _GL(id="x", preparer="alice", approver="manager", amount=10),
        _GL(id="y", preparer="bob", approver="manager", amount=20),
    ]
    hits = unusual_user_hits(entries, rare_threshold=2)
    assert {h["entry_id"] for h in hits} == {"x", "y"}
    assert all("rare preparer" in h["reason"] for h in hits)


def test_late_posting_hits() -> None:
    entries = [
        _GL(id="ok", je_date=date(2024, 1, 1), posting_date=date(2024, 1, 3), amount=10),
        _GL(id="late", je_date=date(2024, 1, 1), posting_date=date(2024, 1, 20), amount=20),
    ]
    hits = late_posting_hits(entries, max_lag_days=5)
    assert [h["entry_id"] for h in hits] == ["late"]
    assert hits[0]["lag_days"] == 19


def test_threshold_hits() -> None:
    entries = [_GL(id="big", amount=100000), _GL(id="small", amount=10)]
    hits = threshold_hits(entries, amount_threshold=1000)
    assert [h["entry_id"] for h in hits] == ["big"]


def test_benford_hits_for_je_amounts() -> None:
    amts = [JEAmount(id=str(i), je_number=None, je_date=None, amount=5000.0 + i) for i in range(60)]
    hits = benford_hits(amts)
    # First digit '5' will be over-represented → most entries flagged.
    assert len(hits) > 10
