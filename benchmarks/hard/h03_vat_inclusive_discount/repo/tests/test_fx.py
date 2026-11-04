from decimal import Decimal

import pytest

from billing.errors import RateNotFound
from billing.fx import ExchangeRates
from billing.money import Money

RATES = {"EUR": "0.92", "GBP": "0.79", "JPY": "152.37", "KWD": "0.3071", "IDR": "16250"}


def test_cross_rate_through_the_base():
    fx = ExchangeRates(rates=RATES)
    assert fx.rate("EUR", "GBP") == Decimal("0.79") / Decimal("0.92")
    assert fx.convert(Money.of("100.00", "EUR"), "GBP") == Money.of("85.87", "GBP")


def test_conversion_rounds_to_the_target_minor_units():
    fx = ExchangeRates(rates=RATES)
    assert fx.convert(Money.of("1.23", "USD"), "JPY") == Money.of("187", "JPY")
    assert fx.convert(Money.of("10.00", "USD"), "KWD") == Money.of("3.071", "KWD")


def test_cross_conversion_rounds_only_once():
    fx = ExchangeRates(rates=RATES)
    # 100 JPY is 0.6563 USD; 0.6563 USD is 0.20155 KWD -> 0.202 (not 0.66 USD -> 0.203)
    assert fx.convert(Money.of("100", "JPY"), "KWD") == Money.of("0.202", "KWD")


def test_explicit_pair_overrides_the_cross_rate_and_inverts():
    fx = ExchangeRates(rates=RATES)
    fx.set_pair("EUR", "GBP", "0.85")
    assert fx.convert(Money.of("100.00", "EUR"), "GBP") == Money.of("85.00", "GBP")
    assert fx.convert(Money.of("85.00", "GBP"), "EUR") == Money.of("100.00", "EUR")
    assert fx.rate("EUR", "JPY") == Decimal("152.37") / Decimal("0.92")  # other pairs unchanged


def test_to_base_and_same_currency():
    fx = ExchangeRates(rates=RATES)
    assert fx.to_base(Money.of("92.00", "EUR")) == Money.of("100.00", "USD")
    assert fx.convert(Money.of("5.555", "EUR"), "EUR") == Money.of("5.56", "EUR")


def test_missing_and_bad_rates():
    fx = ExchangeRates(rates={"EUR": "0.92"})
    with pytest.raises(RateNotFound):
        fx.convert(Money.of("1", "EUR"), "CHF")
    with pytest.raises(ValueError):
        fx.set_rate("CHF", "0")
    with pytest.raises(TypeError):
        fx.set_rate("CHF", 0.9)
