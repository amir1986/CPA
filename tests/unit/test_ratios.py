"""Unit tests for the ratio library."""

from __future__ import annotations

from datetime import date

import pytest

from app.analyze.ratios import TBSnapshot, compute_all, compute_ratio


@pytest.fixture
def snapshot() -> TBSnapshot:
    return TBSnapshot(
        period_end=date(2024, 12, 31),
        by_code={"1000": 500.0, "1100": 200.0, "2000": 300.0, "3000": 400.0, "4000": 1000.0, "5000": 600.0},
        by_type={
            "asset": [500.0, 200.0],         # current 700
            "liability": [300.0],
            "equity": [400.0],
            "revenue": [1000.0],
            "expense": [600.0],
        },
    )


def test_current_ratio(snapshot: TBSnapshot) -> None:
    r = compute_ratio("current_ratio", snapshot)
    assert r.value == pytest.approx(700 / 300)
    assert r.numerator == 700.0
    assert r.denominator == 300.0


def test_debt_to_equity(snapshot: TBSnapshot) -> None:
    r = compute_ratio("debt_to_equity", snapshot)
    assert r.value == pytest.approx(300 / 400)


def test_net_margin(snapshot: TBSnapshot) -> None:
    r = compute_ratio("net_margin", snapshot)
    assert r.value == pytest.approx((1000 - 600) / 1000)


def test_zero_denominator_returns_none() -> None:
    s = TBSnapshot(date(2024, 12, 31), {}, {"asset": [100.0], "liability": []})
    assert compute_ratio("current_ratio", s).value is None


def test_unknown_ratio_raises() -> None:
    with pytest.raises(KeyError):
        compute_ratio("unknown", TBSnapshot(date(2024, 12, 31), {}, {}))


def test_compute_all_returns_full_catalog(snapshot: TBSnapshot) -> None:
    out = compute_all(snapshot)
    names = {r.name for r in out}
    assert {"current_ratio", "debt_to_equity", "gross_margin", "net_margin", "return_on_assets", "return_on_equity"} <= names
