"""Invoices: lines, discounts, tax and totals.

Totals are computed line by line:

1. each line's amount is its charge (credits are negative lines);
2. coupons discount the discountable charge lines (``billing.discounts``), never credits;
3. each line's tax is computed on what remains of the line after its discount
   (``billing.tax.line_tax``) and rounded per line;
4. for exclusive tax, ``total = subtotal - discount + tax``; for inclusive tax the tax is
   already inside the amounts, so ``total = subtotal - discount`` and ``tax`` is the part of
   the total that is tax.

``subtotal``, ``discount`` and ``tax`` are sums of the per-line figures, so an invoice always
reconciles with its lines.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from .dates import Period
from .discounts import Coupon, discount_amounts
from .errors import BillingError, CurrencyMismatch
from .money import Money
from .tax import NO_TAX, TaxRate, line_tax

LINE_KINDS = ("charge", "proration", "credit")
INVOICE_KINDS = ("renewal", "proration", "one_off")
STATUSES = ("draft", "open", "paid", "void", "uncollectible")


@dataclass(frozen=True)
class InvoiceLine:
    description: str
    amount: Money
    quantity: int = 1
    period: Period | None = None
    kind: str = "charge"
    discountable: bool = True
    component: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in LINE_KINDS:
            raise BillingError(f"unknown line kind {self.kind!r}")


@dataclass(frozen=True)
class InvoiceTotals:
    currency: str
    subtotal: Money
    discount: Money
    tax: Money
    total: Money
    line_discounts: tuple[Money, ...]
    line_taxes: tuple[Money, ...]


@dataclass
class Invoice:
    customer_id: str
    currency: str
    lines: list[InvoiceLine] = field(default_factory=list)
    tax_rate: TaxRate = NO_TAX
    coupons: tuple[Coupon, ...] = ()
    kind: str = "renewal"
    period: Period | None = None
    period_index: int | None = None
    subscription_id: str | None = None
    number: str | None = None
    issued_at: datetime | None = None
    status: str = "draft"
    amount_paid: Money | None = None

    def __post_init__(self) -> None:
        if self.kind not in INVOICE_KINDS:
            raise BillingError(f"unknown invoice kind {self.kind!r}")
        if self.amount_paid is None:
            self.amount_paid = Money.zero(self.currency)

    # ------------------------------------------------------------------ building

    def add_line(self, line: InvoiceLine) -> None:
        if self.status != "draft":
            raise BillingError("only draft invoices can be changed")
        if line.amount.currency != self.currency:
            raise CurrencyMismatch(f"line in {line.amount.currency} on a {self.currency} invoice")
        self.lines.append(line)

    def add_lines(self, lines: list[InvoiceLine]) -> None:
        for line in lines:
            self.add_line(line)

    # ------------------------------------------------------------------ totals

    def totals(self) -> InvoiceTotals:
        currency = self.currency
        zero = Money.zero(currency)
        amounts = [line.amount.rounded() for line in self.lines]
        eligible = [
            a if line.discountable and line.kind != "credit" and not a.is_negative() else zero
            for line, a in zip(self.lines, amounts)
        ]
        discounts = discount_amounts(self.coupons, eligible) if self.coupons else [zero] * len(amounts)
        payable = [a - d for a, d in zip(amounts, discounts)]
        if self.tax_rate.inclusive:
            # inclusive prices already contain their tax: take it from the listed price
            taxes = [line_tax(a, self.tax_rate) for a in amounts]
        else:
            taxes = [line_tax(p, self.tax_rate) for p in payable]
        subtotal = Money.total(amounts, currency)
        discount = Money.total(discounts, currency)
        tax = Money.total(taxes, currency)
        if self.tax_rate.inclusive:
            total = subtotal - discount
        else:
            total = subtotal - discount + tax
        return InvoiceTotals(
            currency, subtotal, discount, tax, total, tuple(discounts), tuple(taxes)
        )

    @property
    def total(self) -> Money:
        return self.totals().total

    @property
    def amount_due(self) -> Money:
        due = self.total - self.amount_paid
        return due.clamp_min(Money.zero(self.currency))

    # ------------------------------------------------------------------ lifecycle

    def finalize(self, number: str, issued_at: datetime) -> Invoice:
        if self.status != "draft":
            raise BillingError(f"invoice is already {self.status}")
        if not self.lines:
            raise BillingError("cannot finalize an empty invoice")
        self.number = number
        self.issued_at = issued_at
        self.status = "open" if not self.amount_due.is_zero() else "paid"
        return self

    def record_payment(self, amount: Money) -> Money:
        """Apply ``amount``; returns what was not needed (overpayment)."""
        if self.status != "open":
            raise BillingError(f"cannot pay a {self.status} invoice")
        if amount.currency != self.currency:
            raise CurrencyMismatch(f"payment in {amount.currency} for a {self.currency} invoice")
        due = self.amount_due
        applied = amount if amount <= due else due
        self.amount_paid = self.amount_paid + applied
        if self.amount_due.is_zero():
            self.status = "paid"
        return amount - applied

    def void(self) -> None:
        if self.status not in ("draft", "open"):
            raise BillingError(f"cannot void a {self.status} invoice")
        self.status = "void"

    def mark_uncollectible(self) -> None:
        if self.status != "open":
            raise BillingError(f"cannot write off a {self.status} invoice")
        self.status = "uncollectible"

    def copy_as_draft(self) -> Invoice:
        return replace(self, lines=list(self.lines), number=None, issued_at=None, status="draft")
