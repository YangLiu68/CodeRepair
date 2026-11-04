from datetime import date
from decimal import Decimal

from billing.discounts import Coupon, Redemption
from billing.money import Money
from billing.plans import Component, Plan, Price
from billing.subscriptions import Subscription


def usd(text):
    return Money.of(text, "USD")


def plan(code, price, trial_days=0):
    seats = Component("seats", "Seats", Price("per_unit", "USD", unit_amount=usd(price)))
    return Plan(code, code.title(), "USD", (seats,), trial_days=trial_days)


TEAM, BUSINESS = plan("team", "12.00"), plan("business", "20.00")
SPRING50 = Coupon("SPRING50", percent_off=Decimal("50"), duration="repeating", duration_periods=3)


def discounted(invoice):
    return any(c.code in ("SPRING50", "WELCOME") for c in invoice.coupons)


def test_hidden_upgrade_does_not_use_up_a_repeating_coupon():
    sub = Subscription.start("sub_2290", "cus_2290", plan("team", "12.00", trial_days=14), date(2027, 3, 1))
    sub.redeem(SPRING50, date(2027, 3, 3))
    first = sub.activate()  # period 0, from March 15
    second = sub.renew()  # period 1, from April 15
    upgrade = sub.change_plan(BUSINESS, date(2027, 4, 30))
    third = sub.renew()  # period 2, from May 15
    fourth = sub.renew()
    # periods 0, 1 and 2 are covered, whatever the number of invoices issued in them
    assert [discounted(i) for i in (first, second, upgrade, third, fourth)] == [
        True,
        True,
        True,
        True,
        False,
    ]
    assert third.total == usd("10.00")
    assert fourth.total == usd("20.00")


def test_hidden_coupon_redeemed_mid_period_counts_that_period():
    sub = Subscription.start("sub_1", "cus_1", TEAM, date(2027, 1, 10))
    sub.renew()  # period 1 from February 10, invoiced before the redemption
    two_months = Coupon("TWO", percent_off=Decimal("50"), duration="repeating", duration_periods=2)
    assert sub.redeem(two_months, date(2027, 2, 20)).first_period == 1
    covered = sub.renew()  # period 2: the second covered period
    after = sub.renew()  # period 3: past the coupon
    assert covered.total == usd("6.00")
    assert after.total == usd("12.00")


def test_hidden_once_coupon_covers_every_invoice_of_its_period():
    sub = Subscription.start("sub_1", "cus_1", TEAM, date(2027, 1, 10))
    sub.redeem(Coupon("WELCOME", percent_off=Decimal("25")), date(2027, 1, 12))
    up = sub.change_plan(BUSINESS, date(2027, 1, 15))
    down = sub.change_plan(TEAM, date(2027, 1, 25))
    renewal = sub.renew()
    assert [discounted(i) for i in (up, down, renewal)] == [True, True, False]


def test_hidden_redemption_covers_periods_not_calls():
    redemption = Redemption(SPRING50, first_period=2)
    for _ in range(5):
        assert redemption.applies_to(3)
    assert [redemption.applies_to(i) for i in range(7)] == [
        False,
        False,
        True,
        True,
        True,
        False,
        False,
    ]
