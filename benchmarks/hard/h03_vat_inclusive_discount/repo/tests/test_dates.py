from datetime import date

import pytest

from billing.dates import Period, add_months, month_period, months_between, next_weekday
from billing.errors import InvalidPeriod


def test_add_months_keeps_the_day_when_it_exists():
    assert add_months(date(2027, 1, 15), 1) == date(2027, 2, 15)
    assert add_months(date(2027, 11, 30), 3) == date(2028, 2, 29)
    assert add_months(date(2027, 3, 10), -3) == date(2026, 12, 10)


def test_add_months_clamps_to_the_end_of_shorter_months():
    assert add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months(date(2027, 3, 31), 1) == date(2027, 4, 30)
    assert add_months(date(2027, 2, 28), 1) == date(2027, 3, 28)


def test_months_between():
    assert months_between(date(2027, 1, 31), date(2027, 3, 1)) == 2
    assert months_between(date(2027, 5, 1), date(2027, 1, 1)) == -4


def test_period_is_half_open():
    period = Period(date(2027, 1, 15), date(2027, 2, 15))
    assert date(2027, 1, 15) in period
    assert date(2027, 2, 14) in period
    assert date(2027, 2, 15) not in period
    assert period.days == 31


def test_period_must_end_after_it_starts():
    with pytest.raises(InvalidPeriod):
        Period(date(2027, 1, 2), date(2027, 1, 2))


def test_overlap_and_split():
    jan = month_period(2027, 1)
    assert jan.overlap(Period(date(2027, 1, 20), date(2027, 3, 1))) == Period(
        date(2027, 1, 20), date(2027, 2, 1)
    )
    assert jan.overlap(month_period(2027, 2)) is None
    first, second = jan.split_at(date(2027, 1, 11))
    assert (first.days, second.days) == (10, 21)
    with pytest.raises(InvalidPeriod):
        jan.split_at(jan.start)
    assert jan.remaining_from(date(2027, 1, 22)).days == 10


def test_next_weekday():
    assert next_weekday(date(2027, 3, 5)) == date(2027, 3, 5)  # Friday
    assert next_weekday(date(2027, 3, 6)) == date(2027, 3, 8)  # Saturday -> Monday
    assert next_weekday(date(2027, 3, 7)) == date(2027, 3, 8)
