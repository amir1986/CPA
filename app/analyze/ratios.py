"""Pure-function ratio library.

Each ratio takes a ``TrialBalanceSnapshot`` (a dict of ``code → closing``)
plus an ``accounts_by_type`` lookup, and returns a ``RatioResult`` with the
numerator and denominator pre-computed so the UI can show the breakdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from app.domain.models import RatioResult


@dataclass(frozen=True)
class TBSnapshot:
    """Closing balances for an engagement at a given period_end.

    ``by_code``: account_code → closing balance.
    ``by_type``: account_type ("asset", "liability", ...) → list of closings.
    """

    period_end: date
    by_code: dict[str, float]
    by_type: dict[str, list[float]]


def _sum(snapshot: TBSnapshot, type_: str) -> float:
    return sum(snapshot.by_type.get(type_, []))


def _safe_div(num: float, den: float) -> float | None:
    return num / den if den else None


# ──────────────── liquidity ────────────────


def current_ratio(s: TBSnapshot) -> RatioResult:
    # Note: a full implementation distinguishes "current" assets/liabilities
    # via account.code prefix or a "current" flag on the COA. We approximate
    # with total assets / liabilities for the v1 baseline; users override via
    # ratio_overrides_json.
    num = _sum(s, "asset")
    den = _sum(s, "liability")
    return RatioResult(
        name="current_ratio",
        period_end=s.period_end,
        value=_safe_div(num, den),
        numerator=num,
        denominator=den,
    )


def quick_ratio(s: TBSnapshot) -> RatioResult:
    num = _sum(s, "asset")  # placeholder until "inventory" flag exists on COA
    den = _sum(s, "liability")
    return RatioResult(
        name="quick_ratio",
        period_end=s.period_end,
        value=_safe_div(num, den),
        numerator=num,
        denominator=den,
    )


# ──────────────── solvency ────────────────


def debt_to_equity(s: TBSnapshot) -> RatioResult:
    num = _sum(s, "liability")
    den = _sum(s, "equity")
    return RatioResult(
        name="debt_to_equity",
        period_end=s.period_end,
        value=_safe_div(num, den),
        numerator=num,
        denominator=den,
    )


# ──────────────── profitability ────────────────


def gross_margin(s: TBSnapshot) -> RatioResult:
    revenue = _sum(s, "revenue")
    expense = _sum(s, "expense")
    num = revenue - expense
    return RatioResult(
        name="gross_margin",
        period_end=s.period_end,
        value=_safe_div(num, revenue) if revenue else None,
        numerator=num,
        denominator=revenue,
    )


def net_margin(s: TBSnapshot) -> RatioResult:
    revenue = _sum(s, "revenue")
    expense = _sum(s, "expense")
    num = revenue - expense
    return RatioResult(
        name="net_margin",
        period_end=s.period_end,
        value=_safe_div(num, revenue) if revenue else None,
        numerator=num,
        denominator=revenue,
    )


def return_on_assets(s: TBSnapshot) -> RatioResult:
    revenue = _sum(s, "revenue")
    expense = _sum(s, "expense")
    assets = _sum(s, "asset")
    income = revenue - expense
    return RatioResult(
        name="return_on_assets",
        period_end=s.period_end,
        value=_safe_div(income, assets),
        numerator=income,
        denominator=assets,
    )


def return_on_equity(s: TBSnapshot) -> RatioResult:
    revenue = _sum(s, "revenue")
    expense = _sum(s, "expense")
    equity = _sum(s, "equity")
    income = revenue - expense
    return RatioResult(
        name="return_on_equity",
        period_end=s.period_end,
        value=_safe_div(income, equity),
        numerator=income,
        denominator=equity,
    )


RATIO_CATALOG: dict[str, Callable[[TBSnapshot], RatioResult]] = {
    "current_ratio": current_ratio,
    "quick_ratio": quick_ratio,
    "debt_to_equity": debt_to_equity,
    "gross_margin": gross_margin,
    "net_margin": net_margin,
    "return_on_assets": return_on_assets,
    "return_on_equity": return_on_equity,
}


def compute_ratio(name: str, snapshot: TBSnapshot) -> RatioResult:
    fn = RATIO_CATALOG.get(name)
    if fn is None:
        raise KeyError(f"unknown ratio: {name}")
    return fn(snapshot)


def compute_all(snapshot: TBSnapshot) -> list[RatioResult]:
    return [fn(snapshot) for fn in RATIO_CATALOG.values()]
