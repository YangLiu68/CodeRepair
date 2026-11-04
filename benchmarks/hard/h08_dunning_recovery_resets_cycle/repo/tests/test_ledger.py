from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from billing.discounts import Coupon
from billing.errors import UnbalancedEntry
from billing.invoice import Invoice, InvoiceLine
from billing.ledger import DISCOUNTS, RECEIVABLE, REVENUE, TAX_PAYABLE, Journal, Posting
from billing.money import Money
from billing.tax import TaxRate

DAY = date(2027, 5, 1)


def usd(text):
    return Money.of(text, "USD")


def eur(text):
    return Money.of(text, "EUR")


def test_balanced_entry_is_posted():
    journal = Journal()
    journal.post(DAY, "sale", [Posting("cash:USD", usd("10")), Posting(REVENUE, usd("-10"))])
    assert journal.balance("cash:USD", "USD") == usd("10.00")
    assert journal.balance(REVENUE, "USD") == usd("-10.00")


def test_unbalanced_entry_is_rejected():
    journal = Journal()
    with pytest.raises(UnbalancedEntry):
        journal.post(DAY, "typo", [Posting("cash:USD", usd("10")), Posting(REVENUE, usd("-9"))])
    with pytest.raises(UnbalancedEntry):
        journal.post(DAY, "single", [Posting("cash:USD", usd("10"))])
    assert journal.entries == []


def test_fx_conversion_through_a_clearing_account_is_accepted():
    journal = Journal()
    journal.post(
        DAY,
        "convert 100 USD to EUR",
        [
            Posting("cash:EUR", eur("92.00")),
            Posting("fx-clearing", eur("-92.00")),
            Posting("fx-clearing", usd("100.00")),
            Posting("cash:USD", usd("-100.00")),
        ],
    )
    balances = journal.trial_balance()
    assert balances[("fx-clearing", "EUR")] == eur("-92.00")
    assert balances[("fx-clearing", "USD")] == usd("100.00")


def test_entry_must_balance_in_each_currency():
    journal = Journal()
    with pytest.raises(UnbalancedEntry):
        journal.post(
            DAY, "wrong", [Posting("cash:EUR", eur("100.00")), Posting("cash:USD", usd("-100.00"))]
        )


def test_invoice_entries_balance():
    journal = Journal()
    issued = datetime(2027, 5, 1, tzinfo=timezone.utc)
    exclusive = Invoice("c", "USD", tax_rate=TaxRate("US", Decimal("10")))
    exclusive.add_line(InvoiceLine("Plan", usd("100.00")))
    journal.post_invoice(exclusive.finalize("INV-1", issued))
    inclusive = Invoice(
        "c", "EUR", tax_rate=TaxRate("DE", Decimal("19"), inclusive=True),
        coupons=(Coupon("TEN", percent_off=Decimal("10")),),
    )
    inclusive.add_line(InvoiceLine("Plan", eur("119.00")))
    journal.post_invoice(inclusive.finalize("INV-2", issued))
    assert journal.balance(RECEIVABLE, "USD") == usd("110.00")
    assert journal.balance(TAX_PAYABLE, "USD") == usd("-10.00")
    assert journal.balance(DISCOUNTS, "EUR") == eur("11.90")
    assert journal.balance(RECEIVABLE, "EUR") == eur("107.10")


def test_payment_entry():
    journal = Journal()
    journal.post_payment(DAY, "INV-1", usd("110.00"))
    assert journal.balance("cash:USD", "USD") == usd("110.00")
    assert journal.balance(RECEIVABLE, "USD") == usd("-110.00")
