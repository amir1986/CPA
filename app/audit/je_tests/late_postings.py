"""Late-postings JE check — flag entries posted more than N days after je_date."""

from __future__ import annotations

from typing import Sequence


def late_posting_hits(entries: Sequence[object], *, max_lag_days: int = 5) -> list[dict]:
    out: list[dict] = []
    for e in entries:
        je_date = getattr(e, "je_date", None)
        posting_date = getattr(e, "posting_date", None)
        if je_date is None or posting_date is None:
            continue
        lag = (posting_date - je_date).days
        if lag > max_lag_days:
            out.append({
                "entry_id": getattr(e, "id"),
                "je_date": str(je_date),
                "posting_date": str(posting_date),
                "lag_days": lag,
                "amount": float(getattr(e, "amount", 0.0)),
                "reason": f"posted {lag} days after journal date (threshold {max_lag_days})",
            })
    return out
