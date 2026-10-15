from shop.cart import Cart
from shop.coupons import lookup


def test_hidden_minimum_spend_boundary():
    coupon = lookup("SAVE10")
    assert coupon.is_applicable(5000) is True
    assert coupon.is_applicable(4999) is False


def test_hidden_exact_minimum_across_items():
    cart = Cart()
    for sku, cents in (("a", 1000), ("b", 1500), ("c", 2500)):
        cart.add(sku, cents)
    cart.apply_coupon("SAVE10")
    assert cart.total() == 4500
