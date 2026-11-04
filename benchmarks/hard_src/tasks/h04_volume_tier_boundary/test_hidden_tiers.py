from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from billing.money import Money
from billing.plans import Component, Plan, Price, Tier
from billing.pricing import amount_for
from billing.subscriptions import Subscription
from billing.usage import UsageEvent, UsageLog


def usd(text):
    return Money.of(text, "USD")


def per_call(text):
    return Money(Decimal(text), "USD")  # sub-cent unit price, not rounded


VOLUME = Price(
    "volume", "USD", tiers=(Tier(10, usd("12.00")), Tier(50, usd("10.00")), Tier(None, usd("8.00")))
)


def test_hidden_volume_quantity_on_a_tier_bound():
    assert amount_for(VOLUME, 10) == usd("120.00")
    assert amount_for(VOLUME, 11) == usd("110.00")
    assert amount_for(VOLUME, 50) == usd("500.00")
    assert amount_for(VOLUME, 51) == usd("408.00")
    assert amount_for(VOLUME, 1) == usd("12.00")


def test_hidden_usage_exactly_on_a_bound_is_billed_in_its_tier():
    api = Component(
        "api_calls",
        "API calls",
        Price(
            "volume",
            "USD",
            tiers=(
                Tier(10000, per_call("0.002")),
                Tier(50000, per_call("0.0015")),
                Tier(None, per_call("0.001")),
            ),
        ),
        metered=True,
    )
    base = Component("base", "Platform fee", Price("flat", "USD", unit_amount=usd("29.00")))
    plan = Plan("dev", "Developer", "USD", (base, api))
    usage = UsageLog()
    sub = Subscription.start("sub_8812", "cus_8812", plan, date(2027, 3, 1), usage=usage)
    start = datetime(2027, 3, 1, tzinfo=timezone.utc)
    for day in range(30):
        usage.record(UsageEvent("sub_8812", "api_calls", 330, start + timedelta(days=day, hours=12)))
    usage.record(UsageEvent("sub_8812", "api_calls", 100, datetime(2027, 3, 31, 23, 59, tzinfo=timezone.utc)))
    usage.record(UsageEvent("sub_8812", "api_calls", 5, datetime(2027, 4, 1, 0, 0, tzinfo=timezone.utc)))
    invoice = sub.renew()
    usage_line = next(line for line in invoice.lines if line.component == "api_calls")
    assert usage_line.quantity == 10000
    assert usage_line.amount == usd("20.00")
    assert invoice.total == usd("49.00")


def test_hidden_flat_fee_tier_includes_its_bound():
    price = Price("volume", "USD", tiers=(Tier(5, usd("0"), usd("25.00")), Tier(None, usd("4.00"))))
    assert amount_for(price, 5) == usd("25.00")
    assert amount_for(price, 6) == usd("24.00")


def test_hidden_graduated_is_unaffected():
    graduated = Price("graduated", "USD", tiers=(Tier(100, usd("0.10")), Tier(None, usd("0.05"))))
    assert amount_for(graduated, 100) == usd("10.00")
    assert amount_for(graduated, 101) == usd("10.05")
