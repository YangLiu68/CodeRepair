from datetime import date

import pytest

from billing.dunning import DunningProcess
from billing.errors import BillingError
from billing.money import Money
from billing.plans import Component, Plan, Price
from billing.subscriptions import Subscription

TEAM = Plan(
    "team",
    "Team",
    "USD",
    (Component("seats", "Seats", Price("per_unit", "USD", unit_amount=Money.of("12", "USD"))),),
)


def failing(_invoice, _day):
    return False


def test_retries_are_measured_from_the_first_failure_and_skip_weekends():
    sub = Subscription.start("sub_1", "cus_1", TEAM, date(2027, 2, 4))
    dunning = DunningProcess.begin(sub, sub.invoices[0], date(2027, 3, 4))  # a Thursday
    assert dunning.schedule() == [date(2027, 3, 5), date(2027, 3, 8), date(2027, 3, 11)]
    assert sub.status == "past_due"


def test_exhausted_retries_write_the_invoice_off():
    sub = Subscription.start("sub_1", "cus_1", TEAM, date(2027, 3, 4))
    invoice = sub.invoices[0]
    dunning = DunningProcess.begin(sub, invoice, date(2027, 3, 4))
    assert dunning.run(failing) == "exhausted"
    assert [a.on for a in dunning.attempts] == dunning.schedule()
    assert invoice.status == "uncollectible" and sub.status == "unpaid"
    with pytest.raises(BillingError):
        dunning.retry(failing)


def test_successful_retry_pays_the_invoice():
    sub = Subscription.start("sub_1", "cus_1", TEAM, date(2027, 3, 4))
    invoice = sub.invoices[0]
    dunning = DunningProcess.begin(sub, invoice, date(2027, 3, 4))
    dunning.retry(failing)
    assert dunning.retry(lambda _inv, _day: True).succeeded
    assert dunning.outcome == "recovered"
    assert invoice.status == "paid" and sub.status == "active"
    assert dunning.next_retry() is None


def test_dunning_needs_an_open_invoice():
    sub = Subscription.start("sub_1", "cus_1", TEAM, date(2027, 3, 4))
    invoice = sub.invoices[0]
    invoice.record_payment(invoice.amount_due)
    with pytest.raises(BillingError):
        DunningProcess.begin(sub, invoice, date(2027, 3, 4))
