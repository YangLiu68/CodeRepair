from decimal import Decimal

import pytest

from billing.discounts import Coupon, Redemption, discount_amounts
from billing.errors import CouponError
from billing.money import Money


def usd(text):
    return Money.of(text, "USD")


def test_coupon_validation():
    with pytest.raises(CouponError):
        Coupon("BOTH", percent_off=Decimal("10"), amount_off=usd("5"))
    with pytest.raises(CouponError):
        Coupon("NONE")
    with pytest.raises(CouponError):
        Coupon("REP", percent_off=Decimal("10"), duration="repeating")
    with pytest.raises(CouponError):
        Coupon("ONCE", percent_off=Decimal("10"), duration_periods=2)
    with pytest.raises(CouponError):
        Coupon("BIG", percent_off=Decimal("120"))


def test_redemption_starts_in_its_first_period():
    coupon = Coupon("SPRING", percent_off=Decimal("20"), duration="repeating", duration_periods=3)
    redemption = Redemption(coupon, first_period=2)
    assert not redemption.applies_to(1)
    assert redemption.applies_to(2)
    forever = Redemption(Coupon("VIP", percent_off=Decimal("5"), duration="forever"), 0)
    assert forever.applies_to(0) and forever.applies_to(500)


def test_percent_coupons_stack_on_what_is_left():
    coupons = [Coupon("A", percent_off=Decimal("50")), Coupon("B", percent_off=Decimal("10"))]
    assert discount_amounts(coupons, [usd("100.00")]) == [usd("55.00")]


def test_amount_off_is_capped_at_what_is_left():
    coupons = [Coupon("BIG", amount_off=usd("500.00"))]
    assert discount_amounts(coupons, [usd("30.00"), usd("10.00")]) == [usd("30.00"), usd("10.00")]


def test_amount_off_in_another_currency_is_refused():
    coupons = [Coupon("EU", amount_off=Money.of("5", "EUR"))]
    with pytest.raises(CouponError):
        discount_amounts(coupons, [usd("30.00")])
