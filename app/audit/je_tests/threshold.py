"""Threshold JE check — flag entries above a (typically materiality) amount."""

from __future__ import annotations

from typing import Sequence


def threshold_hits(entries: Sequence[object], *, amount_threshold: float) -> list[dict]:
    out: list[dict] = []
    for e in entries:
        amt = float(getattr(e, "amount", 0.0))
        if abs(amt) >= amount_threshold:
            out.append({
                "entry_id": getattr(e, "id"),
                "amount": amt,
                "reason": f"amount {amt:.2f} ≥ threshold {amount_threshold:.2f}",
            })
    return out
