"""Benford JE test — flag JEs whose absolute net amount has a suspicious first digit.

Strategy: run Benford on the population; flag entries whose first digit is in
the *least-expected* digits (those with observed_pct ≥ expected_pct + 0.05).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.analyze.anomalies import BENFORD_EXPECTED, benford_first_digit, first_digit


@dataclass(frozen=True)
class JEAmount:
    id: str
    je_number: str | None
    je_date: object | None
    amount: float


def benford_hits(entries: Sequence[JEAmount], *, suspicious_lift: float = 0.05) -> list[dict]:
    summary = benford_first_digit(e.amount for e in entries)
    if not summary.observed_pct:
        return []
    suspicious_digits = {
        d for d in range(1, 10)
        if summary.observed_pct.get(d, 0.0) > BENFORD_EXPECTED[d] + suspicious_lift
    }
    out: list[dict] = []
    for e in entries:
        d = first_digit(e.amount)
        if d is None or d not in suspicious_digits:
            continue
        out.append({
            "entry_id": e.id,
            "je_number": e.je_number,
            "je_date": str(e.je_date) if e.je_date else None,
            "amount": e.amount,
            "first_digit": d,
            "reason": f"first-digit {d} over-represented (observed {summary.observed_pct[d]:.3f} vs expected {BENFORD_EXPECTED[d]:.3f})",
        })
    return out
