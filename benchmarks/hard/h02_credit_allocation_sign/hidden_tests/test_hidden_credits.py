from datetime import date

from billing.money import Money
from billing.plans import Component, Plan, Price
from billing.subscriptions import Subscription


def usd(text):
    return Money.of(text, "USD")


def test_hidden_negative_allocation_mirrors_the_positive_one():
    cases = [
        ("10.00", [1, 1, 1]),
        ("0.05", [8, 7, 10]),
        ("100.00", [1, 2, 3, 4, 5, 6, 7]),
        ("7.77", [2, 1]),
        ("45.83", [9000, 2500, 999]),
    ]
    for amount, weights in cases:
        positive = usd(amount).allocate(weights)
        negative = usd("-" + amount).allocate(weights)
        assert negative == [-part for part in positive], (amount, weights)
        assert Money.total(negative, "USD") == usd("-" + amount)


def test_hidden_downgrade_credit_lines_add_up_to_the_unused_amount():
    business = Plan(
        "business",
        "Business",
        "USD",
        (
            Component("seats", "Seats", Price("per_unit", "USD", unit_amount=usd("30.00"))),
            Component("support", "Priority support", Price("flat", "USD", unit_amount=usd("25.00"))),
            Component("storage", "Extra storage", Price("flat", "USD", unit_amount=usd("9.99"))),
        ),
    )
    team = Plan(
        "team",
        "Team",
        "USD",
        (Component("seats", "Seats", Price("per_unit", "USD", unit_amount=usd("12.00"))),),
    )
    sub = Subscription.start("sub_4471", "cus_1", business, date(2027, 4, 10), quantities={"seats": 3})
    invoice = sub.change_plan(team, date(2027, 4, 29), quantities={"seats": 3})  # 11 of 30 days left
    credits = [line.amount for line in invoice.lines if line.amount.is_negative()]
    assert Money.total(credits, "USD") == usd("-45.83")
    assert credits == [-part for part in usd("45.83").allocate([9000, 2500, 999])]
    charges = [line.amount for line in invoice.lines if not line.amount.is_negative()]
    assert charges == [usd("13.20")]
    assert invoice.total == usd("-32.63")


def test_hidden_split_of_a_negative_amount():
    assert usd("-1.00").split(3) == [usd("-0.34"), usd("-0.33"), usd("-0.33")]
    assert Money.of("-100", "JPY").split(3) == [
        Money.of("-34", "JPY"),
        Money.of("-33", "JPY"),
        Money.of("-33", "JPY"),
    ]
