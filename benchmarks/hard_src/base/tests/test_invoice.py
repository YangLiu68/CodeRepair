from datetime import datetime, timezone
from decimal import Decimal

import pytest

from billing.discounts import Coupon
from billing.errors import BillingError, CurrencyMismatch
from billing.invoice import Invoice, InvoiceLine
from billing.money import Money
from billing.tax import TaxRate

SALES_TAX = TaxRate("US-TX", Decimal("8"))
VAT = TaxRate("DE", Decimal("19"), inclusive=True)
TEN_PERCENT = Coupon("TEN", percent_off=Decimal("10"))
ISSUED = datetime(2027, 3, 1, tzinfo=timezone.utc)


def usd(text):
    return Money.of(text, "USD")


def eur(text):
    return Money.of(text, "EUR")


def test_exclusive_tax_after_percent_discount():
    invoice = Invoice("cus_1", "USD", tax_rate=SALES_TAX, coupons=(TEN_PERCENT,))
    invoice.add_lines([InvoiceLine("Seats", usd("50.00")), InvoiceLine("Storage", usd("30.00"))])
    totals = invoice.totals()
    assert totals.line_discounts == (usd("5.00"), usd("3.00"))
    assert totals.line_taxes == (usd("3.60"), usd("2.16"))
    assert (totals.subtotal, totals.discount, totals.tax) == (usd("80.00"), usd("8.00"), usd("5.76"))
    assert totals.total == usd("77.76")


def test_inclusive_vat_without_discount():
    invoice = Invoice("cus_2", "EUR", tax_rate=VAT)
    invoice.add_line(InvoiceLine("Pro plan", eur("119.00")))
    totals = invoice.totals()
    assert (totals.tax, totals.total) == (eur("19.00"), eur("119.00"))


def test_inclusive_vat_is_computed_on_the_discounted_price():
    invoice = Invoice("cus_3", "EUR", tax_rate=VAT, coupons=(TEN_PERCENT,))
    invoice.add_line(InvoiceLine("Pro plan", eur("119.00")))
    totals = invoice.totals()
    assert totals.discount == eur("11.90")
    assert totals.total == eur("107.10")
    assert totals.tax == eur("17.10")


def test_amount_off_coupon_is_spread_in_proportion():
    coupon = Coupon("TENOFF", amount_off=usd("10.00"))
    invoice = Invoice("cus_4", "USD", coupons=(coupon,))
    invoice.add_lines([InvoiceLine("A", usd("60.00")), InvoiceLine("B", usd("40.00"))])
    assert invoice.totals().line_discounts == (usd("6.00"), usd("4.00"))
    assert invoice.total == usd("90.00")


def test_credits_are_not_discounted():
    invoice = Invoice("cus_5", "USD", coupons=(TEN_PERCENT,))
    invoice.add_lines(
        [InvoiceLine("Plan", usd("100.00")), InvoiceLine("Goodwill", usd("-20.00"), kind="credit")]
    )
    totals = invoice.totals()
    assert totals.line_discounts == (usd("10.00"), usd("0.00"))
    assert totals.total == usd("70.00")


def test_payments_and_lifecycle():
    invoice = Invoice("cus_6", "USD")
    with pytest.raises(BillingError):
        invoice.finalize("INV-1", ISSUED)
    invoice.add_line(InvoiceLine("Plan", usd("30.00")))
    with pytest.raises(CurrencyMismatch):
        invoice.add_line(InvoiceLine("Other", eur("1.00")))
    invoice.finalize("INV-1", ISSUED)
    assert invoice.status == "open"
    with pytest.raises(BillingError):
        invoice.add_line(InvoiceLine("Late", usd("1.00")))
    assert invoice.record_payment(usd("10.00")) == usd("0.00")
    assert invoice.amount_due == usd("20.00")
    assert invoice.record_payment(usd("25.00")) == usd("5.00")
    assert invoice.status == "paid"


def test_zero_total_invoice_is_paid_on_finalize():
    coupon = Coupon("FREE", percent_off=Decimal("100"))
    invoice = Invoice("cus_7", "USD", coupons=(coupon,))
    invoice.add_line(InvoiceLine("Plan", usd("30.00")))
    assert invoice.finalize("INV-2", ISSUED).status == "paid"
