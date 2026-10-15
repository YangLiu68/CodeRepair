from textkit import wrap


def test_wrap():
    assert wrap("the quick brown fox", 10) == ["the quick", "brown fox"]


def test_long_word_kept_whole():
    assert wrap("extraordinary", 5) == ["extraordinary"]
