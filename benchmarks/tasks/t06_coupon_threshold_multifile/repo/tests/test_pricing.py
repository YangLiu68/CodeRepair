import pytest

from shop.pricing import apply_percent_discount, format_cents


def test_discount_rounds_down():
    assert apply_percent_discount(999, 10) == 900


def test_discount_rejects_bad_percent():
    with pytest.raises(ValueError):
        apply_percent_discount(100, 101)


def test_format_cents():
    assert format_cents(4500) == "$45.00"
    assert format_cents(-5) == "-$0.05"
