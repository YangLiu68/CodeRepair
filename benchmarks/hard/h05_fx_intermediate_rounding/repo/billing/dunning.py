"""Retrying failed renewal payments ("dunning").

When the payment for a renewal invoice fails, the subscription becomes past_due and the
payment is retried at fixed offsets from the *first* failure (by default 1, 3 and 7 days
later). A retry that falls on a Saturday or Sunday moves to the following Monday; that shift
does not move the retries after it.

* A successful retry pays the invoice and returns the subscription to active. Its billing
  dates do not change and no new invoice is issued: the customer has simply paid late.
* When the last retry fails too, the invoice is written off (uncollectible) and the
  subscription becomes unpaid.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from .dates import next_weekday
from .errors import BillingError
from .invoice import Invoice
from .subscriptions import Subscription

DEFAULT_OFFSETS = (1, 3, 7)

#: ``charge(invoice, day)`` tries to collect the invoice's amount due; True if it succeeded
Charger = Callable[[Invoice, date], bool]


@dataclass
class Attempt:
    on: date
    succeeded: bool


@dataclass
class DunningProcess:
    subscription: Subscription
    invoice: Invoice
    first_failure: date
    offsets: Sequence[int] = DEFAULT_OFFSETS
    attempts: list[Attempt] = field(default_factory=list)
    outcome: str | None = None  # "recovered" | "exhausted"

    @classmethod
    def begin(cls, subscription: Subscription, invoice: Invoice, failed_on: date, **kw):
        """Record the first failure: the subscription becomes past_due."""
        if invoice.status != "open":
            raise BillingError("dunning applies to open invoices only")
        subscription.mark_past_due(failed_on)
        subscription.events.publish(
            "invoice.payment_failed", failed_on, subscription.id, number=invoice.number
        )
        return cls(subscription, invoice, failed_on, **kw)

    def schedule(self) -> list[date]:
        """All retry dates, measured from the first failure."""
        return [next_weekday(self.first_failure + timedelta(days=o)) for o in self.offsets]

    def next_retry(self) -> date | None:
        if self.outcome is not None:
            return None
        pending = self.schedule()[len(self.attempts) :]
        return pending[0] if pending else None

    def retry(self, charge: Charger) -> Attempt:
        """Run the next scheduled retry with ``charge``."""
        day = self.next_retry()
        if day is None:
            raise BillingError("no retry left")
        succeeded = charge(self.invoice, day)
        attempt = Attempt(day, succeeded)
        self.attempts.append(attempt)
        if succeeded:
            self.invoice.record_payment(self.invoice.amount_due)
            self.subscription.recover(day)
            self.subscription.events.publish(
                "invoice.paid", day, self.subscription.id, number=self.invoice.number
            )
            self.outcome = "recovered"
        elif len(self.attempts) == len(self.offsets):
            self.invoice.mark_uncollectible()
            self.subscription.mark_unpaid(day)
            self.subscription.events.publish(
                "invoice.uncollectible", day, self.subscription.id, number=self.invoice.number
            )
            self.outcome = "exhausted"
        return attempt

    def run(self, charge: Charger) -> str:
        """Retry until the payment succeeds or the schedule is exhausted."""
        while self.outcome is None:
            self.retry(charge)
        return self.outcome
