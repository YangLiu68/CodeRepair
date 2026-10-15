import pytest

from timefmt import parse_duration
from timefmt.humanize import humanize_text


def test_hidden_parse_with_spaces():
    assert parse_duration("2d 4h") == 187200
    assert parse_duration("1h 30m 15s") == 5415


def test_hidden_humanize_text_with_spaces():
    assert humanize_text("1h 1s") == "1 hour and 1 second"


def test_hidden_still_rejects_garbage_with_spaces():
    with pytest.raises(ValueError):
        parse_duration("1h thirty")
