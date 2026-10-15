from shop.cart import Cart


def test_subtotal_sums_line_items():
    cart = Cart()
    cart.add("mug", 1250, quantity=2)
    cart.add("tea", 799)
    assert cart.subtotal() == 3299


def test_coupon_applies_above_minimum():
    cart = Cart()
    cart.add("kettle", 6000)
    cart.apply_coupon("SAVE10")
    assert cart.total() == 5400


def test_coupon_ignored_below_minimum():
    cart = Cart()
    cart.add("mug", 4999)
    cart.apply_coupon("SAVE10")
    assert cart.total() == 4999


def test_coupon_applies_at_exact_minimum():
    cart = Cart()
    cart.add("mug", 2500, quantity=2)
    cart.apply_coupon("save10")
    assert cart.total() == 4500
