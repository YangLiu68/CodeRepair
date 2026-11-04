from datetime import date

from billing.dates import Period
from billing.money import Money
from billing.periods import BillingCycle
from billing.plans import Component, Plan, Price
from billing.subscriptions import Subscription

TEAM = Plan(
    "team",
    "Team",
    "USD",
    (Component("seats", "Seats", Price("per_unit", "USD", unit_amount=Money.of("12", "USD"))),),
)


def test_hidden_month_end_anchor_returns_to_the_31st():
    cycle = BillingCycle(date(2027, 1, 31))
    period, starts = cycle.period(0), []
    for _ in range(7):
        starts.append(period.start)
        period = cycle.next_period(period)
    assert starts == [
        date(2027, 1, 31),
        date(2027, 2, 28),
        date(2027, 3, 31),
        date(2027, 4, 30),
        date(2027, 5, 31),
        date(2027, 6, 30),
        date(2027, 7, 31),
    ]


def test_hidden_renewals_keep_the_signup_day():
    sub = Subscription.start("sub_1", "cus_1", TEAM, date(2027, 1, 31))
    periods = [sub.renew().period for _ in range(4)]
    assert periods == [
        Period(date(2027, 2, 28), date(2027, 3, 31)),
        Period(date(2027, 3, 31), date(2027, 4, 30)),
        Period(date(2027, 4, 30), date(2027, 5, 31)),
        Period(date(2027, 5, 31), date(2027, 6, 30)),
    ]
    assert sub.next_billing_date() == date(2027, 6, 30)
    assert [inv.period_index for inv in sub.invoices] == [0, 1, 2, 3, 4]


def test_hidden_quarterly_cycle_across_a_leap_february():
    cycle = BillingCycle(date(2027, 11, 30), interval_months=3)
    first = cycle.period(0)
    second = cycle.next_period(first)
    third = cycle.next_period(second)
    assert first == Period(date(2027, 11, 30), date(2028, 2, 29))
    assert second == Period(date(2028, 2, 29), date(2028, 5, 30))
    assert third == Period(date(2028, 5, 30), date(2028, 8, 30))
