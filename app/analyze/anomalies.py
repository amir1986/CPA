"""Anomaly scans on GL entries.

Phase-1 set: Benford's first-digit law (the classic forensic check) and a
simple z-score per account. Round-amount clustering and dormant-account
activations land alongside the Documents-screen extractors.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence


BENFORD_EXPECTED = {
    1: 0.301, 2: 0.176, 3: 0.125, 4: 0.097, 5: 0.079,
    6: 0.067, 7: 0.058, 8: 0.051, 9: 0.046,
}


@dataclass(frozen=True)
class BenfordResult:
    observed: dict[int, int]
    observed_pct: dict[int, float]
    expected_pct: dict[int, float]
    chi_square: float
    df: int = 8
    n: int = 0
    suspect: bool = False


def first_digit(amount: float) -> int | None:
    a = abs(amount)
    if a < 1e-9:
        return None
    while a < 1:
        a *= 10
    while a >= 10:
        a /= 10
    return int(a)


def benford_first_digit(amounts: Iterable[float]) -> BenfordResult:
    digits: list[int] = []
    for a in amounts:
        d = first_digit(a)
        if d is not None:
            digits.append(d)
    n = len(digits)
    observed = dict(Counter(digits))
    for d in range(1, 10):
        observed.setdefault(d, 0)
    if n == 0:
        return BenfordResult(observed=observed, observed_pct={}, expected_pct=BENFORD_EXPECTED, chi_square=0.0, n=0)
    observed_pct = {d: observed[d] / n for d in range(1, 10)}
    chi_square = 0.0
    for d in range(1, 10):
        exp = BENFORD_EXPECTED[d] * n
        if exp > 0:
            chi_square += (observed[d] - exp) ** 2 / exp
    # 5% critical value for chi-square with df=8 is ≈ 15.51.
    suspect = chi_square > 15.51
    return BenfordResult(
        observed=observed,
        observed_pct=observed_pct,
        expected_pct=BENFORD_EXPECTED,
        chi_square=chi_square,
        n=n,
        suspect=suspect,
    )


@dataclass(frozen=True)
class ZScoreHit:
    account_id: str
    amount: float
    z: float


def z_score_outliers_by_account(
    entries: Sequence[tuple[str, float]],
    *,
    threshold: float = 3.0,
) -> list[ZScoreHit]:
    """Return entries whose absolute z-score (within their account) exceeds threshold."""
    by_account: dict[str, list[float]] = defaultdict(list)
    for account_id, amount in entries:
        by_account[account_id].append(amount)
    out: list[ZScoreHit] = []
    for account_id, amounts in by_account.items():
        n = len(amounts)
        if n < 4:
            continue
        mean = sum(amounts) / n
        variance = sum((a - mean) ** 2 for a in amounts) / max(1, n - 1)
        sd = math.sqrt(variance) if variance > 0 else 0.0
        if sd == 0:
            continue
        for amount in amounts:
            z = (amount - mean) / sd
            if abs(z) >= threshold:
                out.append(ZScoreHit(account_id=account_id, amount=amount, z=z))
    return out
