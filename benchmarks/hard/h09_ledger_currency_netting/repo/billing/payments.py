"""Customer payments, credit balance and refunds.

``Payments.receive`` applies a payment to the customer's open invoices, oldest first (by issue
time, then number). Whatever is left over becomes credit balance in the payment's currency,
which ``apply_credit`` uses up on later invoices before any new payment is asked for.

A refund returns money for a paid invoice; it never exceeds what was paid on that invoice.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from .errors import CurrencyMismatch, PaymentError
from .invoice import Invoice
from .money import Money


@dataclass(frozen=True)
class Receipt:
    customer_id: str
    on: date
    amount: Money
    applied: tuple[tuple[str, Money], ...]  # (invoice number, amount applied)
    credited: Money


@dataclass(frozen=True)
class Refund:
    invoice_number: str
    on: date
    amount: Money


class Payments:
    def __init__(self) -> None:
        self._credit: dict[tuple[str, str], Money] = {}
        self.receipts: list[Receipt] = []
        self.refunds: list[Refund] = []
        self._refunded: dict[str, Money] = {}

    def credit_balance(self, customer_id: str, currency: str) -> Money:
        return self._credit.get((customer_id, currency), Money.zero(currency))

    def receive(
        self, customer_id: str, amount: Money, on: date, invoices: Iterable[Invoice]
    ) -> Receipt:
        """Apply a payment to ``invoices`` (the customer's, open ones only), oldest first."""
        if not amount.amount > 0:
            raise PaymentError("payments must be positive")
        candidates = [
            inv
            for inv in invoices
            if inv.customer_id == customer_id
            and inv.status == "open"
            and inv.currency == amount.currency
        ]
        candidates.sort(key=lambda inv: (inv.issued_at, inv.number))
        left = amount.rounded()
        applied = []
        for invoice in candidates:
            if left.is_zero():
                break
            due = invoice.amount_due
            rest = invoice.record_payment(left)
            applied.append((invoice.number, due - invoice.amount_due))
            left = rest
        if not left.is_zero():
            key = (customer_id, amount.currency)
            self._credit[key] = self.credit_balance(customer_id, amount.currency) + left
        receipt = Receipt(customer_id, on, amount.rounded(), tuple(applied), left)
        self.receipts.append(receipt)
        return receipt

    def apply_credit(self, invoice: Invoice) -> Money:
        """Use the customer's credit balance on ``invoice``; returns the amount used."""
        if invoice.status != "open":
            return Money.zero(invoice.currency)
        key = (invoice.customer_id, invoice.currency)
        balance = self.credit_balance(*key)
        if balance.is_zero():
            return balance
        due = invoice.amount_due
        used = balance if balance <= due else due
        invoice.record_payment(used)
        self._credit[key] = balance - used
        return used

    def refund(self, invoice: Invoice, amount: Money, on: date) -> Refund:
        if invoice.status != "paid":
            raise PaymentError("only paid invoices can be refunded")
        if amount.currency != invoice.currency:
            raise CurrencyMismatch("refund currency differs from the invoice")
        already = self._refunded.get(invoice.number, Money.zero(invoice.currency))
        if not amount.amount > 0 or already + amount > invoice.amount_paid:
            raise PaymentError("refund must be positive and at most what was paid")
        self._refunded[invoice.number] = already + amount
        refund = Refund(invoice.number, on, amount.rounded())
        self.refunds.append(refund)
        return refund

    def refunded(self, invoice: Invoice) -> Money:
        return self._refunded.get(invoice.number, Money.zero(invoice.currency))
