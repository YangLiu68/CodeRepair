from datetime import date, datetime, timezone

import pytest

from billing.errors import PaymentError
from billing.invoice import Invoice, InvoiceLine
from billing.money import Money
from billing.payments import Payments


def usd(text):
    return Money.of(text, "USD")


def open_invoice(number, amount, day, customer="cus_1"):
    invoice = Invoice(customer, "USD")
    invoice.add_line(InvoiceLine("Plan", usd(amount)))
    return invoice.finalize(number, datetime(2027, 1, day, tzinfo=timezone.utc))


def test_payment_goes_to_the_oldest_invoice_first_and_the_rest_to_credit():
    newer, older = open_invoice("INV-2", "30.00", 20), open_invoice("INV-1", "50.00", 5)
    payments = Payments()
    receipt = payments.receive("cus_1", usd("100.00"), date(2027, 1, 25), [newer, older])
    assert receipt.applied == (("INV-1", usd("50.00")), ("INV-2", usd("30.00")))
    assert receipt.credited == usd("20.00")
    assert payments.credit_balance("cus_1", "USD") == usd("20.00")


def test_credit_is_used_on_the_next_invoice():
    payments = Payments()
    payments.receive("cus_1", usd("20.00"), date(2027, 1, 2), [])
    invoice = open_invoice("INV-3", "12.00", 3)
    assert payments.apply_credit(invoice) == usd("12.00")
    assert invoice.status == "paid"
    assert payments.credit_balance("cus_1", "USD") == usd("8.00")


def test_other_customers_invoices_are_not_touched():
    mine, theirs = open_invoice("INV-4", "10.00", 4), open_invoice("INV-5", "10.00", 1, "cus_2")
    Payments().receive("cus_1", usd("10.00"), date(2027, 1, 5), [theirs, mine])
    assert (mine.status, theirs.status) == ("paid", "open")


def test_refunds_are_limited_to_what_was_paid():
    invoice = open_invoice("INV-6", "40.00", 6)
    payments = Payments()
    with pytest.raises(PaymentError):
        payments.refund(invoice, usd("1.00"), date(2027, 1, 7))
    payments.receive("cus_1", usd("40.00"), date(2027, 1, 7), [invoice])
    payments.refund(invoice, usd("25.00"), date(2027, 1, 8))
    with pytest.raises(PaymentError):
        payments.refund(invoice, usd("15.01"), date(2027, 1, 9))
    payments.refund(invoice, usd("15.00"), date(2027, 1, 9))
    assert payments.refunded(invoice) == usd("40.00")
