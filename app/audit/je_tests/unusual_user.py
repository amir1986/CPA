"""Unusual-user check: preparer==approver (segregation-of-duties violation) and rare preparers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence


def unusual_user_hits(entries: Sequence[object], *, rare_threshold: int = 3) -> list[dict]:
    counts: Counter[str] = Counter()
    for e in entries:
        p = getattr(e, "preparer", None)
        if p:
            counts[p] += 1
    rare = {p for p, c in counts.items() if c <= rare_threshold}

    out: list[dict] = []
    for e in entries:
        preparer = getattr(e, "preparer", None)
        approver = getattr(e, "approver", None)
        reasons = []
        if preparer and approver and preparer == approver:
            reasons.append(f"preparer==approver ({preparer})")
        if preparer and preparer in rare:
            reasons.append(f"rare preparer ({preparer}, n={counts[preparer]})")
        if reasons:
            out.append({
                "entry_id": e.id,
                "amount": float(getattr(e, "amount", 0.0)),
                "preparer": preparer,
                "approver": approver,
                "reason": "; ".join(reasons),
            })
    return out
