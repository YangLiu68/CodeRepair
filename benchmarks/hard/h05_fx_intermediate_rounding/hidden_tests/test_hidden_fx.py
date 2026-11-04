from decimal import Decimal

from billing.fx import ExchangeRates
from billing.money import Money

RATES = {"EUR": "0.92", "GBP": "0.79", "JPY": "152.37", "KWD": "0.3071", "IDR": "16250"}


def exact(amount, source, target):
    rate = Decimal(RATES[target]) / Decimal(RATES[source])
    return Money(Decimal(amount) * rate, target).rounded()


def test_hidden_cross_conversions_round_once():
    fx = ExchangeRates(rates=RATES)
    cases = [
        ("100", "JPY", "KWD"),
        ("250", "JPY", "KWD"),
        ("0.99", "EUR", "JPY"),
        ("19.99", "GBP", "JPY"),
        ("1999", "JPY", "EUR"),
        ("1000000", "IDR", "KWD"),
    ]
    for amount, source, target in cases:
        assert fx.convert(Money.of(amount, source), target) == exact(amount, source, target), (
            amount,
            source,
            target,
        )


def test_hidden_large_amounts_keep_their_precision():
    fx = ExchangeRates(rates=RATES)
    assert fx.convert(Money.of("123456789", "JPY"), "KWD") == exact("123456789", "JPY", "KWD")
    assert fx.convert(Money.of("99999.99", "EUR"), "IDR") == exact("99999.99", "EUR", "IDR")


def test_hidden_pairs_and_base_conversions_unchanged():
    fx = ExchangeRates(rates=RATES)
    fx.set_pair("JPY", "KWD", "0.00201")
    assert fx.convert(Money.of("100", "JPY"), "KWD") == Money.of("0.201", "KWD")
    assert fx.convert(Money.of("100.00", "USD"), "JPY") == Money.of("15237", "JPY")
    assert fx.to_base(Money.of("100", "JPY")) == Money.of("0.66", "USD")
    assert Money.of("2.345", "USD") == Money.of("2.35", "USD")
