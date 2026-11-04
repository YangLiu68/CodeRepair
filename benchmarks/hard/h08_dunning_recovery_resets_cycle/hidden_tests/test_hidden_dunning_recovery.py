from datetime import date

from billing.dates import Period
from billing.dunning import DunningProcess
from billing.money import Money
from billing.plans import Component, Plan, Price
from billing.subscriptions import Subscription

TEAM = Plan(
    "team",
    "Team",
    "USD",
    (Component("seats", "Seats", Price("per_unit", "USD", unit_amount=Money.of("12", "USD"))),),
)


def second_try_succeeds():
    calls = []

    def charge(_invoice, day):
        calls.append(day)
        return len(calls) == 2

    return charge


def failed_renewal():
    sub = Subscription.start("sub_5120", "cus_5120", TEAM, date(2027, 2, 3))
    sub.invoices[0].record_payment(sub.invoices[0].amount_due)
    renewal = sub.renew()  # March 3
    return sub, renewal, DunningProcess.begin(sub, renewal, date(2027, 3, 3))


def test_hidden_recovered_subscription_keeps_its_billing_dates():
    sub, renewal, dunning = failed_renewal()
    assert dunning.run(second_try_succeeds()) == "recovered"
    assert [a.on for a in dunning.attempts] == [date(2027, 3, 4), date(2027, 3, 8)]
    assert sub.status == "active"
    assert sub.current_period == Period(date(2027, 3, 3), date(2027, 4, 3))
    assert sub.next_billing_date() == date(2027, 4, 3)
    assert sub.renew().period == Period(date(2027, 4, 3), date(2027, 5, 3))


def test_hidden_recovery_issues_no_new_invoice():
    sub, renewal, dunning = failed_renewal()
    dunning.run(second_try_succeeds())
    assert renewal.status == "paid"
    assert len(sub.invoices) == 2
    assert len(sub.events.of_type("invoice.created")) == 2
    assert [e.on for e in sub.events.of_type("invoice.paid")] == [date(2027, 3, 8)]


def test_hidden_exhausted_dunning_still_ends_unpaid():
    sub, renewal, dunning = failed_renewal()
    assert dunning.run(lambda _invoice, _day: False) == "exhausted"
    assert (sub.status, renewal.status) == ("unpaid", "uncollectible")
