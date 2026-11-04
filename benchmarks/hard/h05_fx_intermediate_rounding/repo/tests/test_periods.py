from datetime import date

import pytest

from billing.dates import Period
from billing.errors import InvalidPeriod
from billing.periods import BillingCycle


def test_monthly_periods_from_a_mid_month_anchor():
    cycle = BillingCycle(date(2027, 1, 15))
    assert cycle.period(0) == Period(date(2027, 1, 15), date(2027, 2, 15))
    assert cycle.period(11) == Period(date(2027, 12, 15), date(2028, 1, 15))


def test_index_of_and_period_containing():
    cycle = BillingCycle(date(2027, 1, 15))
    assert cycle.index_of(date(2027, 1, 15)) == 0
    assert cycle.index_of(date(2027, 2, 14)) == 0
    assert cycle.index_of(date(2027, 2, 15)) == 1
    assert cycle.period_containing(date(2027, 7, 1)) == Period(date(2027, 6, 15), date(2027, 7, 15))
    with pytest.raises(InvalidPeriod):
        cycle.index_of(date(2027, 1, 14))


def test_next_period_follows_on():
    cycle = BillingCycle(date(2027, 1, 15))
    assert cycle.next_period(cycle.period(0)) == cycle.period(1)
    assert cycle.next_period(cycle.period(5)).start == date(2027, 7, 15)


def test_quarterly_cycle():
    cycle = BillingCycle(date(2027, 1, 10), interval_months=3)
    assert [p.start for p in (cycle.period(i) for i in range(3))] == [
        date(2027, 1, 10),
        date(2027, 4, 10),
        date(2027, 7, 10),
    ]
    assert cycle.index_of(date(2027, 4, 9)) == 0


def test_interval_must_be_a_supported_length():
    with pytest.raises(ValueError):
        BillingCycle(date(2027, 1, 1), interval_months=2)
