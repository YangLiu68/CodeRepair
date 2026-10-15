from textkit import slugify


def test_hidden_transliterates_accents():
    assert slugify("Café Crème!") == "cafe-creme"


def test_hidden_mixed_accents():
    assert slugify("Ångström Über naïve") == "angstrom-uber-naive"


def test_hidden_non_latin_letters_are_dropped():
    assert slugify("日本 rocks") == "rocks"
