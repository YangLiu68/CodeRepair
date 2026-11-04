"""An in-memory event log, the source for webhooks and audit trails."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

EVENT_TYPES = (
    "subscription.created",
    "subscription.updated",
    "subscription.canceled",
    "invoice.created",
    "invoice.paid",
    "invoice.payment_failed",
    "invoice.uncollectible",
)


@dataclass(frozen=True)
class Event:
    type: str
    on: date
    subject_id: str
    data: dict[str, Any] = field(default_factory=dict)


class EventLog:
    def __init__(self) -> None:
        self._events: list[Event] = []
        self._handlers: dict[str, list[Callable[[Event], None]]] = {}

    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {event_type!r}")
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event_type: str, on: date, subject_id: str, **data: Any) -> Event:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {event_type!r}")
        event = Event(event_type, on, subject_id, dict(data))
        self._events.append(event)
        for handler in self._handlers.get(event_type, []):
            handler(event)
        return event

    def of_type(self, event_type: str) -> list[Event]:
        return [e for e in self._events if e.type == event_type]

    def __iter__(self):
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)
