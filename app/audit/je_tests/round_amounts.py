"""Round-amount JE check — flag entries whose absolute amount is an exact round value."""

from __future__ import annotations

from typing import Sequence


def is_round(amount: float, *, units: int = 1000) -> bool:
    a = abs(amount)
    if a < units:
        return False
    return abs(a - round(a / units) * units) < 1e-6


def round_amount_hits(entries: Sequence[object], *, units: int = 1000) -> list[dict]:
    out: list[dict] = []
    for e in entries:
        amt = float(getattr(e, "amount", 0.0))
        if is_round(amt, units=units):
            out.append({
                "entry_id": getattr(e, "id"),
                "amount": amt,
                "reason": f"amount is an exact multiple of {units}",
            })
    return out
