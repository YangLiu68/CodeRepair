import pytest

from ledger.money import format_cents, split_evenly, to_cents


def test_to_cents_whole_and_simple():
    assert to_cents("10") == 1000
    assert to_cents("19.99") == 1999


def test_to_cents_rounds_half_up():
    assert to_cents("1.005") == 101


def test_split_evenly_distributes_remainder():
    assert split_evenly(100, 3) == [34, 33, 33]


def test_split_evenly_rejects_zero_ways():
    with pytest.raises(ValueError):
        split_evenly(100, 0)


def test_format_cents():
    assert format_cents(1234) == "12.34"
    assert format_cents(-5) == "-0.05"
