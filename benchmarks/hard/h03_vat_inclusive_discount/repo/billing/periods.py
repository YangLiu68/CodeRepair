"""Billing cycles: consecutive periods anchored to a start date.

A ``BillingCycle`` anchored on January 31 with a one-month interval bills on the anchor's
day of the month whenever the month has it, and on the month's last day otherwise:
January 31, February 28, March 31, April 30, May 31, ... A short month does not move the
billing day permanently. Periods are numbered from 0 (the period starting at the anchor)
and are half-open, so each period ends where the next one starts.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

from .dates import Period, add_months, months_between
from .errors import InvalidPeriod


@dataclass(frozen=True)
class BillingCycle:
    anchor: date
    interval_months: int = 1

    def __post_init__(self) -> None:
        if self.interval_months not in (1, 3, 6, 12):
            raise ValueError("interval_months must be 1, 3, 6 or 12")

    def period_start(self, index: int) -> date:
        """First day of period ``index``."""
        if index < 0:
            raise InvalidPeriod("period indices start at 0")
        return add_months(self.anchor, index * self.interval_months)

    def period(self, index: int) -> Period:
        return Period(self.period_start(index), self.period_start(index + 1))

    def index_of(self, day: date) -> int:
        """Index of the period that contains ``day``."""
        if day < self.anchor:
            raise InvalidPeriod(f"{day} is before the cycle anchor {self.anchor}")
        index = max(0, months_between(self.anchor, day) // self.interval_months)
        while index > 0 and self.period_start(index) > day:
            index -= 1
        while self.period_start(index + 1) <= day:
            index += 1
        return index

    def period_containing(self, day: date) -> Period:
        return self.period(self.index_of(day))

    def next_period(self, current: Period) -> Period:
        """The period after ``current``, which must be one of this cycle's periods."""
        index = self.index_of(current.start)
        if self.period(index) != current:
            raise InvalidPeriod(f"{current} is not a period of this cycle")
        return self.period(index + 1)

    def periods(self, start_index: int = 0) -> Iterator[Period]:
        index = start_index
        while True:
            yield self.period(index)
            index += 1
