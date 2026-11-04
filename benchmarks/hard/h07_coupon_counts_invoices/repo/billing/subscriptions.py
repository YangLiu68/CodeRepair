"""Subscriptions: trials, renewals, plan changes, coupons, payment status and cancellation.

Status transitions::

    trialing  --activate-->            active
    active    --renew-->               active     next period, renewal invoice
    active    --payment failed-->      past_due   (billing.dunning)
    past_due  --payment recovered-->   active     billing dates unchanged, no new invoice
    past_due  --retries exhausted-->   unpaid
    past_due, unpaid, canceled  --reactivate(on)-->  active
                                       a *new* billing cycle starting on ``on``, invoiced
    any       --cancel-->              canceled (now, or at the end of the current period)

Licensed components are invoiced in advance, at the start of each period. Metered components
are invoiced in arrears: the renewal invoice for a period also bills the usage of the period
that just ended.

Every invoice belongs to the period it was issued in (``Invoice.period_index``); coupons are
applied by period (``billing.discounts``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from .discounts import Coupon, Redemption
from .errors import CouponError, InvalidPeriod, InvalidTransition
from .events import EventLog
from .ids import InvoiceNumberer
from .invoice import Invoice, InvoiceLine
from .periods import BillingCycle
from .plans import Plan
from .pricing import amount_for
from .proration import charge_lines, credit_lines
from .tax import NO_TAX, TaxRate
from .usage import UsageLog

STATUSES = ("trialing", "active", "past_due", "unpaid", "canceled")


def _issue_time(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=timezone.utc)


@dataclass
class Subscription:
    id: str
    customer_id: str
    plan: Plan
    cycle: BillingCycle
    quantities: dict[str, int]
    tax_rate: TaxRate = NO_TAX
    status: str = "active"
    trial_end: date | None = None
    current_period: object = None  # Period once billing has started
    redemptions: list[Redemption] = field(default_factory=list)
    invoices: list[Invoice] = field(default_factory=list)
    usage: UsageLog = field(default_factory=UsageLog)
    events: EventLog = field(default_factory=EventLog)
    numberer: InvoiceNumberer = field(default_factory=InvoiceNumberer)
    cancel_at_period_end: bool = False
    canceled_on: date | None = None

    # ------------------------------------------------------------------ creation

    @classmethod
    def start(
        cls,
        id: str,
        customer_id: str,
        plan: Plan,
        on: date,
        *,
        quantities: Mapping[str, int] | None = None,
        tax_rate: TaxRate = NO_TAX,
        usage: UsageLog | None = None,
        events: EventLog | None = None,
        numberer: InvoiceNumberer | None = None,
    ) -> Subscription:
        """A new subscription: trialing if the plan has a trial, otherwise active and invoiced."""
        trial_end = on + timedelta(days=plan.trial_days) if plan.trial_days else None
        subscription = cls(
            id=id,
            customer_id=customer_id,
            plan=plan,
            cycle=BillingCycle(trial_end or on, plan.interval_months),
            quantities=_quantities(plan, quantities),
            tax_rate=tax_rate,
            status="trialing" if trial_end else "active",
            trial_end=trial_end,
            usage=usage if usage is not None else UsageLog(),
            events=events if events is not None else EventLog(),
            numberer=numberer if numberer is not None else InvoiceNumberer(),
        )
        subscription.events.publish("subscription.created", on, id, plan=plan.code)
        if trial_end is None:
            subscription.current_period = subscription.cycle.period(0)
            subscription._issue(subscription._licensed_lines(), "renewal", on)
        return subscription

    # ------------------------------------------------------------------ queries

    @property
    def period_index(self) -> int:
        if self.current_period is None:
            raise InvalidTransition("billing has not started")
        return self.cycle.index_of(self.current_period.start)

    def next_billing_date(self) -> date | None:
        if self.status == "trialing":
            return self.trial_end
        if self.status in ("canceled", "unpaid") or self.cancel_at_period_end:
            return None
        return self.current_period.end

    # ------------------------------------------------------------------ lifecycle

    def activate(self, on: date | None = None) -> Invoice:
        """Convert a trial into a paid subscription and invoice its first period.

        Without ``on`` the first paid period starts at ``trial_end``. Ending the trial early
        (``on`` before ``trial_end``) re-anchors the billing cycle on ``on``.
        """
        if self.status != "trialing":
            raise InvalidTransition(f"cannot activate a {self.status} subscription")
        if on is not None and on != self.trial_end:
            if on > self.trial_end:
                raise InvalidTransition("the trial has already ended")
            self.cycle = BillingCycle(on, self.plan.interval_months)
            self.trial_end = on
        self.status = "active"
        self.current_period = self.cycle.period(0)
        self.events.publish("subscription.updated", self.current_period.start, self.id)
        return self._issue(self._licensed_lines(), "renewal", self.current_period.start)

    def renew(self) -> Invoice | None:
        """Move to the next period and invoice it (or end a subscription set to cancel)."""
        if self.status not in ("active", "past_due"):
            raise InvalidTransition(f"cannot renew a {self.status} subscription")
        previous = self.current_period
        if self.cancel_at_period_end:
            self.status = "canceled"
            self.canceled_on = previous.end
            self.events.publish("subscription.canceled", previous.end, self.id)
            return None
        self.current_period = self.cycle.next_period(previous)
        lines = self._licensed_lines() + self._usage_lines(previous)
        return self._issue(lines, "renewal", self.current_period.start)

    def change_plan(
        self, new_plan: Plan, on: date, *, quantities: Mapping[str, int] | None = None
    ) -> Invoice | None:
        """Switch plans on ``on``.

        During a trial the plan simply changes (nothing has been charged yet). Otherwise the
        unused part of the old plan is credited and the rest of the period on the new plan is
        charged, on one proration invoice dated ``on``. Plans must share interval and currency.
        """
        if (new_plan.interval_months, new_plan.currency) != (
            self.plan.interval_months,
            self.plan.currency,
        ):
            raise InvalidTransition("plan changes keep the billing interval and currency")
        if self.status == "trialing":
            self.plan = new_plan
            self.quantities = _quantities(new_plan, quantities)
            return None
        if self.status != "active":
            raise InvalidTransition(f"cannot change the plan of a {self.status} subscription")
        period = self.current_period
        if on not in period:
            raise InvalidPeriod(f"{on} is outside the current period {period}")
        old_lines = self._licensed_lines()
        self.plan = new_plan
        self.quantities = _quantities(new_plan, quantities)
        lines = credit_lines(old_lines, period, on) + charge_lines(self._licensed_lines(), period, on)
        self.events.publish("subscription.updated", on, self.id, plan=new_plan.code)
        if not lines:
            return None
        return self._issue(lines, "proration", on)

    def redeem(self, coupon: Coupon, on: date) -> Redemption:
        """Attach ``coupon`` from the period that contains ``on`` (period 0 during a trial)."""
        if any(r.coupon.code == coupon.code for r in self.redemptions):
            raise CouponError(f"{coupon.code} is already redeemed on {self.id}")
        if self.status in ("canceled", "unpaid"):
            raise CouponError(f"cannot redeem a coupon on a {self.status} subscription")
        first = 0 if on < self.cycle.anchor else self.cycle.index_of(on)
        redemption = Redemption(coupon, first)
        self.redemptions.append(redemption)
        return redemption

    # ------------------------------------------------------------------ payment status

    def mark_past_due(self, on: date) -> None:
        if self.status != "active":
            raise InvalidTransition(f"cannot mark a {self.status} subscription past due")
        self.status = "past_due"
        self.events.publish("subscription.updated", on, self.id, status="past_due")

    def recover(self, on: date) -> None:
        """A late payment succeeded: back to active, same billing dates, no new invoice."""
        if self.status != "past_due":
            raise InvalidTransition(f"cannot recover a {self.status} subscription")
        self.status = "active"
        self.events.publish("subscription.updated", on, self.id, status="active")

    def mark_unpaid(self, on: date) -> None:
        if self.status != "past_due":
            raise InvalidTransition(f"cannot mark a {self.status} subscription unpaid")
        self.status = "unpaid"
        self.events.publish("subscription.updated", on, self.id, status="unpaid")

    def reactivate(self, on: date) -> Invoice:
        """Restart billing from ``on`` (support action, or a customer coming back).

        A new billing cycle is anchored on ``on`` and its first period is invoiced at once.
        Allowed from past_due, unpaid and canceled.
        """
        if self.status not in ("past_due", "unpaid", "canceled"):
            raise InvalidTransition(f"cannot reactivate a {self.status} subscription")
        self.cycle = BillingCycle(on, self.plan.interval_months)
        self.status = "active"
        self.cancel_at_period_end = False
        self.canceled_on = None
        self.current_period = self.cycle.period(0)
        self.events.publish("subscription.updated", on, self.id, status="active")
        return self._issue(self._licensed_lines(), "renewal", on)

    def cancel(self, on: date, *, at_period_end: bool = True) -> None:
        if self.status == "canceled":
            raise InvalidTransition("already canceled")
        if at_period_end and self.status in ("active", "past_due"):
            self.cancel_at_period_end = True
            self.events.publish("subscription.updated", on, self.id, cancel_at_period_end=True)
            return
        self.status = "canceled"
        self.canceled_on = on
        self.events.publish("subscription.canceled", on, self.id)

    # ------------------------------------------------------------------ invoicing

    def _licensed_lines(self) -> list[InvoiceLine]:
        lines = []
        for component in self.plan.licensed:
            quantity = self.quantities.get(component.code, 1)
            lines.append(
                InvoiceLine(
                    f"{self.plan.name}: {component.description}",
                    amount_for(component.price, quantity),
                    quantity=quantity,
                    period=self.current_period,
                    component=component.code,
                )
            )
        return lines

    def _usage_lines(self, period) -> list[InvoiceLine]:
        lines = []
        for component in self.plan.metered:
            quantity = self.usage.total(self.id, component.code, period)
            if quantity == 0:
                continue
            lines.append(
                InvoiceLine(
                    f"{component.description} ({quantity:,} in {period})",
                    amount_for(component.price, quantity),
                    quantity=quantity,
                    period=period,
                    component=component.code,
                )
            )
        return lines

    def _issue(self, lines: list[InvoiceLine], kind: str, on: date) -> Invoice:
        index = self.period_index
        applied = [r for r in self.redemptions if r.applies_to(index)]
        for redemption in applied:
            redemption.record_use()
        coupons = tuple(r.coupon for r in applied)
        invoice = Invoice(
            self.customer_id,
            self.plan.currency,
            tax_rate=self.tax_rate,
            coupons=coupons,
            kind=kind,
            period=self.current_period,
            period_index=index,
            subscription_id=self.id,
        )
        invoice.add_lines(lines)
        issued_at = _issue_time(on)
        invoice.finalize(self.numberer.next_number(issued_at), issued_at)
        self.invoices.append(invoice)
        self.events.publish("invoice.created", on, self.id, number=invoice.number)
        return invoice


def _quantities(plan: Plan, given: Mapping[str, int] | None) -> dict[str, int]:
    given = dict(given or {})
    unknown = set(given) - {c.code for c in plan.licensed}
    if unknown:
        raise KeyError(f"plan {plan.code} has no licensed components {sorted(unknown)}")
    if any(q < 0 for q in given.values()):
        raise ValueError("quantities cannot be negative")
    return {c.code: given.get(c.code, 1) for c in plan.licensed}
