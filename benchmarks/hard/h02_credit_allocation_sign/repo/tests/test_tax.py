from decimal import Decimal

import pytest

from billing.money import Money
from billing.tax import TaxRate, TaxTable, line_tax, tax_in_gross, tax_on_net

NY = TaxRate("US-NY", Decimal("8.875"))
DE = TaxRate("DE", Decimal("19"), inclusive=True)


def test_exclusive_tax_is_added_on_top():
    assert tax_on_net(Money.of("100.00", "USD"), NY) == Money.of("8.88", "USD")


def test_inclusive_tax_is_contained_in_the_gross_amount():
    assert tax_in_gross(Money.of("119.00", "EUR"), DE) == Money.of("19.00", "EUR")
    assert tax_in_gross(Money.of("10.00", "EUR"), DE) == Money.of("1.60", "EUR")


def test_line_tax_dispatches_on_the_rate():
    assert line_tax(Money.of("119.00", "EUR"), DE) == Money.of("19.00", "EUR")
    assert line_tax(Money.of("100.00", "USD"), NY) == Money.of("8.88", "USD")
    assert line_tax(Money.of("-50.00", "USD"), NY) == Money.of("-4.44", "USD")


def test_exempt_customers_pay_no_tax_and_keep_inclusive_prices():
    table = TaxTable()
    table.add(DE)
    table.exempt("cus_charity")
    rate = table.rate_for("DE", "cus_charity")
    assert rate.is_zero and rate.inclusive
    assert table.rate_for("DE", "cus_other") == DE
    with pytest.raises(KeyError):
        table.rate_for("FR")


def test_percent_must_be_sane():
    with pytest.raises(ValueError):
        TaxRate("X", Decimal("100"))
