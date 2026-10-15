import pytest

from timefmt import format_duration, parse_duration


@pytest.mark.parametrize(
    "text,expected",
    [("90s", 90), ("1h30m", 5400), ("2d4h", 187200), ("45M", 2700)],
)
def test_parse_compact(text, expected):
    assert parse_duration(text) == expected


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_duration("soon")


def test_parse_rejects_out_of_order_units():
    with pytest.raises(ValueError):
        parse_duration("30m1h")


def test_format_roundtrip():
    for seconds in (0, 59, 3600, 93784):
        assert parse_duration(format_duration(seconds)) == seconds
