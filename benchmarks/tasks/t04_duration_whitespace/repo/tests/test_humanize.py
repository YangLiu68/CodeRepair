from timefmt.humanize import humanize, humanize_text


def test_humanize_multiple_units():
    assert humanize(3725) == "1 hour, 2 minutes and 5 seconds"


def test_humanize_text():
    assert humanize_text("2h") == "2 hours"
