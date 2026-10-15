# SAVE10 not applied when the cart total is exactly $50.00

Our promo says "10% off orders of $50 or more". A cart with two $25.00 mugs shows a
checkout total of $50.00 instead of $45.00 after applying SAVE10. Carts at $50.01 get
the discount as expected.

`tests/test_cart.py::test_coupon_applies_at_exact_minimum` fails:

```
    assert cart.total() == 4500
E   assert 5000 == 4500
```
