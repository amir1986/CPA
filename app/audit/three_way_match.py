"""Three-way match: PO ↔ GR ↔ invoice.

Inputs are three lists of typed tuples; outputs an exception list per
mismatch (amount, quantity, vendor) plus the cleanly matched set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class PORecord:
    po_number: str
    vendor: str
    quantity: float
    amount: float


@dataclass(frozen=True)
class GRRecord:
    po_number: str
    quantity_received: float


@dataclass(frozen=True)
class InvoiceRecord:
    po_number: str
    vendor: str
    amount: float


@dataclass(frozen=True)
class ThreeWayException:
    po_number: str
    reason: str
    detail: dict[str, float | str]


def three_way_match(
    pos: Sequence[PORecord],
    grs: Sequence[GRRecord],
    invoices: Sequence[InvoiceRecord],
    *,
    amount_tolerance: float = 0.01,
    quantity_tolerance: float = 0.001,
) -> tuple[list[str], list[ThreeWayException]]:
    by_po_grs = {gr.po_number: gr for gr in grs}
    by_po_inv = {inv.po_number: inv for inv in invoices}
    matched: list[str] = []
    exceptions: list[ThreeWayException] = []
    for po in pos:
        gr = by_po_grs.get(po.po_number)
        inv = by_po_inv.get(po.po_number)
        if gr is None:
            exceptions.append(ThreeWayException(po.po_number, "missing GR", {}))
            continue
        if inv is None:
            exceptions.append(ThreeWayException(po.po_number, "missing invoice", {}))
            continue
        if abs(gr.quantity_received - po.quantity) > quantity_tolerance:
            exceptions.append(
                ThreeWayException(
                    po.po_number,
                    "quantity mismatch",
                    {"po_qty": po.quantity, "gr_qty": gr.quantity_received},
                )
            )
            continue
        if abs(inv.amount - po.amount) > amount_tolerance:
            exceptions.append(
                ThreeWayException(
                    po.po_number,
                    "amount mismatch",
                    {"po_amount": po.amount, "invoice_amount": inv.amount},
                )
            )
            continue
        if inv.vendor != po.vendor:
            exceptions.append(
                ThreeWayException(
                    po.po_number,
                    "vendor mismatch",
                    {"po_vendor": po.vendor, "invoice_vendor": inv.vendor},
                )
            )
            continue
        matched.append(po.po_number)
    return matched, exceptions
