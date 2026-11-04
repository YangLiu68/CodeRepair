"""Metered usage: recording events and totalling them per billing period.

Usage is attributed to billing periods by the calendar date of its timestamp (timestamps are
UTC). Periods are half-open (see ``billing.dates``): an event dated on a period's ``end`` belongs
to the *next* period, never to both. This is what makes a period's total independent of when
the invoice is produced.

Events may carry an idempotency key. Recording an event whose key was already seen is a no-op
(clients retry on timeouts), so totals never double count retried events.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from .dates import Period

AGGREGATIONS = ("sum", "max", "last")


@dataclass(frozen=True)
class UsageEvent:
    subscription_id: str
    component: str
    quantity: int
    timestamp: datetime
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise ValueError("usage quantity cannot be negative")
        if self.timestamp.tzinfo is None:
            raise ValueError("usage timestamps must be timezone-aware")


class UsageLog:
    def __init__(self, events: Iterable[UsageEvent] = ()) -> None:
        self._events: list[UsageEvent] = []
        self._keys: set[str] = set()
        for event in events:
            self.record(event)

    def record(self, event: UsageEvent) -> bool:
        """Store ``event``; False (and nothing stored) for an already seen idempotency key."""
        if event.idempotency_key is not None:
            if event.idempotency_key in self._keys:
                return False
            self._keys.add(event.idempotency_key)
        self._events.append(event)
        return True

    def events(self, subscription_id: str, component: str, period: Period) -> list[UsageEvent]:
        """Events of one component in ``period``, oldest first."""
        selected = [
            e
            for e in self._events
            if e.subscription_id == subscription_id
            and e.component == component
            and e.timestamp.astimezone(timezone.utc).date() in period
        ]
        return sorted(selected, key=lambda e: e.timestamp)

    def total(
        self, subscription_id: str, component: str, period: Period, aggregation: str = "sum"
    ) -> int:
        """The billable quantity for ``period``: sum of events, their maximum, or the last one."""
        if aggregation not in AGGREGATIONS:
            raise ValueError(f"aggregation must be one of {AGGREGATIONS}")
        events = self.events(subscription_id, component, period)
        if not events:
            return 0
        if aggregation == "sum":
            return sum(e.quantity for e in events)
        if aggregation == "max":
            return max(e.quantity for e in events)
        return events[-1].quantity

    def __len__(self) -> int:
        return len(self._events)
