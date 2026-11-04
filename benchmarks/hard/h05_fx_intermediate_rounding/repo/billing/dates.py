"""Calendar arithmetic: month steps, half-open periods and weekdays.

Every period in this library is half-open. ``Period(date(2027, 1, 15), date(2027, 2, 15))``
covers January 15 up to, but not including, February 15; February 15 is the first day of
the following period. ``Period.days`` is therefore simply ``end - start``.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

from .errors import InvalidPeriod


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def add_months(day: date, months: int) -> date:
    """``day`` moved by whole calendar months (negative to go back).

    The day of the month is kept when the target month has it and clamped to the target
    month's last day when it does not: ``add_months(date(2027, 1, 31), 1)`` is
    February 28, 2027 and ``add_months(date(2028, 1, 31), 1)`` is February 29, 2028.
    """
    index = day.year * 12 + (day.month - 1) + months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    return date(year, month, min(day.day, days_in_month(year, month)))


def months_between(start: date, end: date) -> int:
    """Whole calendar months from ``start`` to ``end`` ignoring the day (may be negative)."""
    return (end.year - start.year) * 12 + (end.month - start.month)


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def next_weekday(day: date) -> date:
    """``day`` itself on Monday to Friday, otherwise the following Monday."""
    while is_weekend(day):
        day += timedelta(days=1)
    return day


@dataclass(frozen=True, order=True)
class Period:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise InvalidPeriod(f"period must end after it starts: {self.start} .. {self.end}")

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    def __contains__(self, day: object) -> bool:
        return isinstance(day, date) and self.start <= day < self.end

    def overlap(self, other: Period) -> Period | None:
        start, end = max(self.start, other.start), min(self.end, other.end)
        return Period(start, end) if start < end else None

    def split_at(self, day: date) -> tuple[Period, Period]:
        """``[start, day)`` and ``[day, end)``; ``day`` must be strictly inside."""
        if not self.start < day < self.end:
            raise InvalidPeriod(f"{day} is not strictly inside {self}")
        return Period(self.start, day), Period(day, self.end)

    def remaining_from(self, day: date) -> Period:
        """``[day, end)``: the part of the period from ``day`` on (``day`` inside the period)."""
        if day not in self:
            raise InvalidPeriod(f"{day} is not inside {self}")
        return Period(day, self.end)

    def iter_days(self) -> Iterator[date]:
        day = self.start
        while day < self.end:
            yield day
            day += timedelta(days=1)

    def __str__(self) -> str:
        return f"{self.start.isoformat()}..{self.end.isoformat()}"


def month_period(year: int, month: int) -> Period:
    start = date(year, month, 1)
    return Period(start, add_months(start, 1))
