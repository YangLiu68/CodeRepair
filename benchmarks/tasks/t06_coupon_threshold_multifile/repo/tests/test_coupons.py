import pytest

from shop.coupons import lookup


def test_lookup_is_case_insensitive():
    assert lookup(" save10 ").code == "SAVE10"


def test_unknown_coupon():
    with pytest.raises(KeyError):
        lookup("FREE")
