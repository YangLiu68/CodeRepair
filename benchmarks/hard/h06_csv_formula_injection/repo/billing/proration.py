"""Proration of plan changes in the middle of a billing period.

When a subscription changes plan on ``day`` inside ``period``, the customer gets a credit for
the unused part of what they paid for the old plan and a charge for the rest of the period on
the new plan. The unused fraction counts whole days: ``(period.end - day) / period.days``.

Credits and charges are computed per invoice: the total is the fraction of the old (or new)
plan's licensed amount, rounded once, and then split across the plan's lines in proportion to
their amounts with ``Money.allocate``. The prorated lines therefore add up exactly to the
rounded total, which is what invoices, payments and the ledger reconcile against.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from .dates import Period
from .invoice import InvoiceLine
from .money import Money


def unused_fraction(period: Period, day: date) -> Decimal:
    """Share of ``period`` from ``day`` (inclusive) to the end, in whole days."""
    remaining = period.remaining_from(day)
    return Decimal(remaining.days) / Decimal(period.days)


def _prorate(
    lines: Sequence[InvoiceLine], period: Period, day: date, *, credit: bool, label: str
) -> list[InvoiceLine]:
    charged = [line for line in lines if not line.amount.is_zero()]
    if not charged:
        return []
    currency = charged[0].amount.currency
    full = Money.total((line.amount for line in charged), currency)
    total = (full * unused_fraction(period, day)).rounded()
    if credit:
        total = -total
    if total.is_zero():
        return []
    parts = total.allocate([abs(line.amount.minor) for line in charged])
    remaining = period.remaining_from(day)
    return [
        InvoiceLine(
            f"{label} {line.description} ({remaining})",
            part,
            quantity=line.quantity,
            period=remaining,
            kind="proration",
            discountable=not credit,
            component=line.component,
        )
        for line, part in zip(charged, parts)
    ]


def credit_lines(old_lines: Sequence[InvoiceLine], period: Period, day: date) -> list[InvoiceLine]:
    """Negative lines crediting the unused part of ``old_lines``."""
    return _prorate(old_lines, period, day, credit=True, label="Unused time on")


def charge_lines(new_lines: Sequence[InvoiceLine], period: Period, day: date) -> list[InvoiceLine]:
    """Positive lines charging the remaining part of the period on ``new_lines``."""
    return _prorate(new_lines, period, day, credit=False, label="Remaining time on")
