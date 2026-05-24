"""Weekend / public-holiday posting check."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date


# Saturday=5, Sunday=6. Israeli week typically Fri+Sat — caller picks via ``weekend_days``.
def weekend_holiday_hits(
    entries: Sequence[object],
    *,
    holidays: Iterable[date] = (),
    weekend_days: Iterable[int] = (5, 6),
) -> list[dict]:
    """Each entry must expose ``id``, ``posting_date`` (or ``je_date``) and ``amount``."""
    holidays_set = set(holidays)
    weekend_set = set(weekend_days)
    out: list[dict] = []
    for e in entries:
        d = getattr(e, "posting_date", None) or getattr(e, "je_date", None)
        if d is None:
            continue
        if d.weekday() in weekend_set or d in holidays_set:
            out.append({
                "entry_id": e.id,
                "je_date": str(d),
                "amount": float(getattr(e, "amount", 0.0)),
                "reason": "posted on weekend" if d.weekday() in weekend_set else "posted on public holiday",
            })
    return out
