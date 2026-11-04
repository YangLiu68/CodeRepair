"""A double-entry journal for invoices, payments and refunds.

Each posting moves a signed amount into an account: positive is a debit, negative a credit.
An entry is accepted only if it balances *in every currency it touches*: for each currency, its
postings sum to zero. An entry may use several currencies, for example a conversion booked
through an FX clearing account (``Dr cash:EUR 92 EUR / Cr fx-clearing 92 EUR`` and
``Dr fx-clearing 100 USD / Cr cash:USD 100 USD``), but amounts in different currencies are
never netted against each other, and balances are always kept per (account, currency).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from .errors import UnbalancedEntry
from .invoice import Invoice
from .money import Money

RECEIVABLE = "accounts-receivable"
REVENUE = "revenue"
TAX_PAYABLE = "tax-payable"
DISCOUNTS = "discounts-given"
CASH = "cash"


@dataclass(frozen=True)
class Posting:
    account: str
    amount: Money  # positive: debit, negative: credit


@dataclass(frozen=True)
class Entry:
    on: date
    memo: str
    postings: tuple[Posting, ...]

    def currencies(self) -> set[str]:
        return {p.amount.currency for p in self.postings}


class Journal:
    def __init__(self) -> None:
        self.entries: list[Entry] = []

    def post(self, on: date, memo: str, postings: Iterable[Posting]) -> Entry:
        postings = tuple(p for p in postings if not p.amount.rounded().is_zero())
        if len(postings) < 2:
            raise UnbalancedEntry(f"{memo}: an entry needs at least two non-zero postings")
        sums: dict[str, Money] = {}
        for posting in postings:
            currency = posting.amount.currency
            sums[currency] = sums.get(currency, Money.zero(currency)) + posting.amount.rounded()
        unbalanced = {c: s for c, s in sums.items() if not s.is_zero()}
        if unbalanced:
            detail = ", ".join(f"{s} off" for s in unbalanced.values())
            raise UnbalancedEntry(f"{memo}: does not balance ({detail})")
        entry = Entry(on, memo, postings)
        self.entries.append(entry)
        return entry

    def balance(self, account: str, currency: str) -> Money:
        total = Money.zero(currency)
        for entry in self.entries:
            for posting in entry.postings:
                if posting.account == account and posting.amount.currency == currency:
                    total = total + posting.amount.rounded()
        return total

    def trial_balance(self) -> dict[tuple[str, str], Money]:
        """Balance of every (account, currency) that has postings."""
        totals: dict[tuple[str, str], Money] = defaultdict(lambda: None)  # type: ignore[arg-type]
        for entry in self.entries:
            for posting in entry.postings:
                key = (posting.account, posting.amount.currency)
                current = totals[key] or Money.zero(posting.amount.currency)
                totals[key] = current + posting.amount.rounded()
        return dict(totals)

    # ------------------------------------------------------------------ standard entries

    def post_invoice(self, invoice: Invoice) -> Entry:
        """Dr receivable (total) and discounts; Cr revenue and tax payable.

        Revenue is the subtotal net of tax: the subtotal itself for exclusive tax, the
        subtotal minus the contained tax for inclusive tax (discounts are booked gross).
        """
        t = invoice.totals()
        revenue = t.subtotal - t.tax if invoice.tax_rate.inclusive else t.subtotal
        postings = [
            Posting(RECEIVABLE, t.total),
            Posting(DISCOUNTS, t.discount),
            Posting(REVENUE, -revenue),
            Posting(TAX_PAYABLE, -t.tax),
        ]
        return self.post(invoice.issued_at.date(), f"invoice {invoice.number}", postings)

    def post_payment(self, on: date, invoice_number: str, amount: Money) -> Entry:
        return self.post(
            on,
            f"payment for {invoice_number}",
            [Posting(f"{CASH}:{amount.currency}", amount), Posting(RECEIVABLE, -amount)],
        )
