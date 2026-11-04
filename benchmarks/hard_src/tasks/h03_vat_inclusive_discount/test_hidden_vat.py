from datetime import datetime, timezone
from decimal import Decimal

from billing.discounts import Coupon
from billing.invoice import Invoice, InvoiceLine
from billing.ledger import TAX_PAYABLE, Journal
from billing.money import Money
from billing.tax import TaxRate, TaxTable

VAT = TaxRate("DE", Decimal("19"), inclusive=True)


def eur(text):
    return Money.of(text, "EUR")


def test_hidden_inclusive_vat_on_several_discounted_lines():
    invoice = Invoice("c", "EUR", tax_rate=VAT, coupons=(Coupon("TWENTY", percent_off=Decimal("20")),))
    invoice.add_lines([InvoiceLine("Pro", eur("119.00")), InvoiceLine("Add-on", eur("59.50"))])
    totals = invoice.totals()
    assert totals.line_discounts == (eur("23.80"), eur("11.90"))
    assert totals.line_taxes == (eur("15.20"), eur("7.60"))
    assert (totals.tax, totals.total) == (eur("22.80"), eur("142.80"))


def test_hidden_inclusive_vat_with_an_amount_off_coupon():
    invoice = Invoice("c", "EUR", tax_rate=VAT, coupons=(Coupon("OFF", amount_off=eur("23.80")),))
    invoice.add_lines([InvoiceLine("Pro", eur("119.00")), InvoiceLine("Seat", eur("119.00"))])
    totals = invoice.totals()
    assert totals.line_discounts == (eur("11.90"), eur("11.90"))
    assert totals.tax == eur("34.20")
    assert totals.total == eur("214.20")


def test_hidden_exempt_customer_and_exclusive_tax_are_unchanged():
    table = TaxTable()
    table.add(VAT)
    table.exempt("charity")
    invoice = Invoice(
        "charity", "EUR", tax_rate=table.rate_for("DE", "charity"),
        coupons=(Coupon("TEN", percent_off=Decimal("10")),),
    )
    invoice.add_line(InvoiceLine("Pro", eur("119.00")))
    assert (invoice.totals().tax, invoice.total) == (eur("0.00"), eur("107.10"))
    us = Invoice("c", "USD", tax_rate=TaxRate("US-NY", Decimal("8.875")),
                 coupons=(Coupon("TEN", percent_off=Decimal("10")),))
    us.add_line(InvoiceLine("Pro", Money.of("100.00", "USD")))
    assert us.totals().tax == Money.of("7.99", "USD")


def test_hidden_ledger_books_the_vat_actually_contained():
    invoice = Invoice("c", "EUR", tax_rate=VAT, coupons=(Coupon("TEN", percent_off=Decimal("10")),))
    invoice.add_line(InvoiceLine("Pro", eur("119.00")))
    invoice.finalize("INV-1", datetime(2027, 5, 1, tzinfo=timezone.utc))
    journal = Journal()
    journal.post_invoice(invoice)
    assert journal.balance(TAX_PAYABLE, "EUR") == eur("-17.10")
