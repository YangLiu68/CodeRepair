import pytest

from billing.formatting import format_money, parse_amount
from billing.money import Money


def test_parse_amount_variants():
    assert parse_amount("$1,234.50", "USD") == Money.of("1234.50", "USD")
    assert parse_amount("1234.5", "USD") == Money.of("1234.50", "USD")
    assert parse_amount("CHF 1'250.00", "CHF") == Money.of("1250.00", "CHF")
    assert parse_amount("-12.50", "EUR") == Money.of("-12.50", "EUR")
    assert parse_amount("¥1,500", "JPY") == Money.of("1500", "JPY")


def test_parse_amount_rejects_ambiguous_or_malformed_text():
    for text in ("12,50", "1,2345", "abc", "1.234", ""):
        with pytest.raises(ValueError):
            parse_amount(text, "USD")


def test_format_money():
    assert format_money(Money.of("1234.5", "USD")) == "$1,234.50"
    assert format_money(Money.of("-12.5", "USD")) == "-$12.50"
    assert format_money(Money.of("-12.5", "USD"), accounting=True) == "($12.50)"
    assert format_money(Money.of("1500", "JPY")) == "¥1,500"
    assert format_money(Money.of("1250", "SEK")) == "1 250,00 kr"
    assert format_money(Money.of("0.202", "KWD")) == "KD 0.202"
