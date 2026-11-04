from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from billing.dates import Period
from billing.discounts import Coupon
from billing.errors import InvalidTransition
from billing.money import Money
from billing.plans import Component, Plan, Price, Tier
from billing.subscriptions import Subscription
from billing.usage import UsageEvent, UsageLog


def usd(text):
    return Money.of(text, "USD")


def seats(price):
    return Component("seats", "Seats", Price("per_unit", "USD", unit_amount=usd(price)))


TEAM = Plan("team", "Team", "USD", (seats("12.00"),))
BUSINESS = Plan("business", "Business", "USD", (seats("20.00"),))
TRIAL = Plan("team-trial", "Team", "USD", (seats("12.00"),), trial_days=14)
API = Component(
    "api_calls",
    "API calls",
    Price("graduated", "USD", tiers=(Tier(1000, usd("0")), Tier(None, usd("0.01")))),
    metered=True,
)
METERED = Plan("dev", "Developer", "USD", (seats("10.00"), API))


def test_start_invoices_the_first_period_in_advance():
    sub = Subscription.start("sub_1", "cus_1", TEAM, date(2027, 1, 10), quantities={"seats": 5})
    assert sub.status == "active"
    (invoice,) = sub.invoices
    assert invoice.period == Period(date(2027, 1, 10), date(2027, 2, 10))
    assert invoice.total == usd("60.00")
    assert invoice.number == "INV-2027-00001" and invoice.status == "open"


def test_renew_moves_to_the_next_period():
    sub = Subscription.start("sub_1", "cus_1", TEAM, date(2027, 1, 10))
    invoice = sub.renew()
    assert invoice.period == Period(date(2027, 2, 10), date(2027, 3, 10))
    assert invoice.period_index == 1
    assert sub.next_billing_date() == date(2027, 3, 10)


def test_trial_then_activation_at_trial_end():
    sub = Subscription.start("sub_1", "cus_1", TRIAL, date(2027, 3, 1))
    assert sub.status == "trialing" and sub.invoices == []
    assert sub.next_billing_date() == date(2027, 3, 15)
    invoice = sub.activate()
    assert invoice.period == Period(date(2027, 3, 15), date(2027, 4, 15))


def test_ending_a_trial_early_re_anchors_the_cycle():
    sub = Subscription.start("sub_1", "cus_1", TRIAL, date(2027, 3, 1))
    invoice = sub.activate(date(2027, 3, 6))
    assert invoice.period == Period(date(2027, 3, 6), date(2027, 4, 6))
    assert sub.renew().period.start == date(2027, 4, 6)


def test_metered_usage_is_billed_in_arrears():
    usage = UsageLog()
    sub = Subscription.start("sub_1", "cus_1", METERED, date(2027, 3, 1), usage=usage)
    usage.record(UsageEvent("sub_1", "api_calls", 1500, datetime(2027, 3, 9, tzinfo=timezone.utc)))
    invoice = sub.renew()
    amounts = [line.amount for line in invoice.lines]
    assert amounts == [usd("10.00"), usd("5.00")]
    assert invoice.lines[1].period == Period(date(2027, 3, 1), date(2027, 4, 1))


def test_upgrade_mid_period_credits_unused_time_and_charges_the_rest():
    sub = Subscription.start("sub_1", "cus_1", TEAM, date(2027, 4, 10), quantities={"seats": 5})
    invoice = sub.change_plan(BUSINESS, date(2027, 4, 30), quantities={"seats": 5})
    assert invoice.kind == "proration"
    # 10 of the period's 30 days remain: -60.00 / 3 and 100.00 / 3
    assert [line.amount for line in invoice.lines] == [usd("-20.00"), usd("33.33")]
    assert invoice.total == usd("13.33")
    assert sub.renew().total == usd("100.00")


def test_proration_credit_splits_across_components():
    plan_a = Plan(
        "a",
        "A",
        "USD",
        (seats("30.00"), Component("support", "Support", Price("flat", "USD", unit_amount=usd("30.00")))),
    )
    sub = Subscription.start("sub_1", "cus_1", plan_a, date(2027, 4, 10), quantities={"seats": 1})
    invoice = sub.change_plan(TEAM, date(2027, 4, 25))  # 15 of 30 days left
    credits = [line.amount for line in invoice.lines if line.amount.is_negative()]
    assert credits == [usd("-15.00"), usd("-15.00")]


def test_plan_change_during_trial_has_no_charges():
    sub = Subscription.start("sub_1", "cus_1", TRIAL, date(2027, 3, 1))
    assert sub.change_plan(Plan("biz-trial", "Biz", "USD", (seats("20.00"),), trial_days=14), date(2027, 3, 5)) is None
    assert sub.invoices == []


def test_repeating_coupon_redeemed_in_a_trial_covers_the_first_periods():
    sub = Subscription.start("sub_1", "cus_1", TRIAL, date(2027, 1, 1))
    coupon = Coupon("Q1", percent_off=Decimal("50"), duration="repeating", duration_periods=3)
    assert sub.redeem(coupon, date(2027, 1, 5)).first_period == 0
    totals = [sub.activate().total] + [sub.renew().total for _ in range(3)]
    assert totals == [usd("6.00"), usd("6.00"), usd("6.00"), usd("12.00")]


def test_once_coupon_covers_the_period_it_was_redeemed_in():
    sub = Subscription.start("sub_1", "cus_1", TEAM, date(2027, 1, 10))
    sub.redeem(Coupon("WELCOME", percent_off=Decimal("25")), date(2027, 1, 20))
    upgrade = sub.change_plan(BUSINESS, date(2027, 1, 20))
    assert upgrade.coupons and upgrade.coupons[0].code == "WELCOME"
    assert sub.renew().coupons == ()


def test_cancel_at_period_end():
    sub = Subscription.start("sub_1", "cus_1", TEAM, date(2027, 1, 10))
    sub.cancel(date(2027, 1, 20))
    assert sub.next_billing_date() is None
    assert sub.renew() is None
    assert sub.status == "canceled" and sub.canceled_on == date(2027, 2, 10)


def test_reactivating_an_unpaid_subscription_starts_a_new_cycle():
    sub = Subscription.start("sub_1", "cus_1", TEAM, date(2027, 1, 10))
    sub.mark_past_due(date(2027, 1, 10))
    sub.mark_unpaid(date(2027, 1, 17))
    invoice = sub.reactivate(date(2027, 2, 3))
    assert sub.status == "active"
    assert invoice.period == Period(date(2027, 2, 3), date(2027, 3, 3))
    assert len(sub.invoices) == 2


def test_support_can_restart_a_past_due_subscription_on_a_new_date():
    sub = Subscription.start("sub_1", "cus_1", TEAM, date(2027, 1, 10))
    sub.mark_past_due(date(2027, 1, 10))
    invoice = sub.reactivate(date(2027, 1, 25))
    assert invoice.period.start == date(2027, 1, 25)
    assert sub.next_billing_date() == date(2027, 2, 25)


def test_invalid_transitions():
    sub = Subscription.start("sub_1", "cus_1", TEAM, date(2027, 1, 10))
    with pytest.raises(InvalidTransition):
        sub.activate()
    with pytest.raises(InvalidTransition):
        sub.mark_unpaid(date(2027, 1, 11))
    with pytest.raises(InvalidTransition):
        sub.reactivate(date(2027, 1, 11))
