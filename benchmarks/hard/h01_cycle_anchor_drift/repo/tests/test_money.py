from decimal import Decimal

import pytest

from billing.errors import CurrencyMismatch, UnknownCurrency
from billing.money import Money


def usd(text):
    return Money.of(text, "USD")


def test_of_rounds_half_away_from_zero():
    assert usd("2.345") == usd("2.35")
    assert usd("-2.345") == usd("-2.35")
    assert Money.of("100.5", "JPY").amount == Decimal("101")


def test_minor_units_follow_the_currency():
    assert usd("12.50").minor == 1250
    assert Money.of("0.202", "KWD").minor == 202
    assert Money.from_minor(1250, "JPY") == Money.of("1250", "JPY")


def test_currencies_do_not_mix():
    with pytest.raises(CurrencyMismatch):
        usd("1") + Money.of("1", "EUR")
    with pytest.raises(CurrencyMismatch):
        usd("1") < Money.of("1", "EUR")
    with pytest.raises(UnknownCurrency):
        Money.of("1", "XXX")


def test_float_is_refused():
    with pytest.raises(TypeError):
        Money.of(0.1, "USD")
    with pytest.raises(TypeError):
        usd("1") * 0.5


def test_arithmetic_keeps_precision_until_rounded():
    third = usd("10") * (Decimal(1) / 3)
    assert third.amount != Decimal("3.33")
    assert third.rounded() == usd("3.33")


def test_allocate_adds_up_and_prefers_largest_remainders():
    assert usd("10.00").allocate([1, 1, 1]) == [usd("3.34"), usd("3.33"), usd("3.33")]
    assert usd("1.00").allocate([3, 1]) == [usd("0.75"), usd("0.25")]
    # 2 cents in thirds of 1, 1, 1: the remainders tie, earlier parts win
    assert usd("0.02").allocate([1, 1, 1]) == [usd("0.01"), usd("0.01"), usd("0.00")]
    parts = usd("100.00").allocate([1, 2, 3, 4, 5, 6, 7])
    assert sum(p.minor for p in parts) == 10000


def test_allocate_by_remainder_not_by_position():
    # exact shares 1.6, 1.4 and 2.0 cents (weights 8, 7, 10 of 5 cents)
    assert usd("0.05").allocate([8, 7, 10]) == [usd("0.02"), usd("0.01"), usd("0.02")]


def test_allocate_and_split_in_zero_decimal_currency():
    yen = Money.of("100", "JPY")
    assert yen.split(3) == [Money.of("34", "JPY"), Money.of("33", "JPY"), Money.of("33", "JPY")]


def test_allocate_rejects_bad_weights():
    with pytest.raises(ValueError):
        usd("1").allocate([])
    with pytest.raises(ValueError):
        usd("1").allocate([0, 0])
    with pytest.raises(ValueError):
        usd("1").allocate([1, -1])


def test_total_and_clamp():
    assert Money.total([usd("1.10"), usd("2.20")], "USD") == usd("3.30")
    assert Money.total([], "EUR") == Money.zero("EUR")
    assert usd("-1").clamp_min(Money.zero("USD")) == Money.zero("USD")
