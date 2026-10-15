from textkit import slugify


def test_basic():
    assert slugify("Hello, World!") == "hello-world"


def test_collapses_separators():
    assert slugify("a  --  b") == "a-b"


def test_strips_edges():
    assert slugify("  --Hi--  ") == "hi"


def test_max_length_does_not_end_with_hyphen():
    assert slugify("word " * 30, max_length=10) == "word-word"


def test_only_punctuation_gives_empty_slug():
    assert slugify("!!!") == ""
