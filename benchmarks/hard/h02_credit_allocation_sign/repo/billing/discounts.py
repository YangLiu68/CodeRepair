"""Coupons, their redemption on a subscription, and per-line discount amounts.

Duration of a coupon is measured in *billing periods* of the subscription it is redeemed on,
starting with the period in which it was redeemed (``Redemption.first_period``):

* ``once``: invoices for the redemption period only;
* ``repeating`` with ``duration_periods = n``: invoices for periods ``first_period`` up to
  ``first_period + n - 1``;
* ``forever``: every later invoice.

Every invoice that belongs to a covered period is discounted, renewal and proration invoices
alike: the number of invoices issued does not matter, so an upgrade in the middle of a period
neither uses up nor extends a coupon.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from .errors import CouponError
from .money import Money

DURATIONS = ("once", "repeating", "forever")


@dataclass(frozen=True)
class Coupon:
    code: str
    percent_off: Decimal | None = None
    amount_off: Money | None = None
    duration: str = "once"
    duration_periods: int | None = None

    def __post_init__(self) -> None:
        if (self.percent_off is None) == (self.amount_off is None):
            raise CouponError(f"{self.code}: give exactly one of percent_off and amount_off")
        if self.percent_off is not None:
            if not isinstance(self.percent_off, Decimal):
                object.__setattr__(self, "percent_off", Decimal(str(self.percent_off)))
            if not 0 < self.percent_off <= 100:
                raise CouponError(f"{self.code}: percent_off must be in (0, 100]")
        if self.amount_off is not None and not self.amount_off.amount > 0:
            raise CouponError(f"{self.code}: amount_off must be positive")
        if self.duration not in DURATIONS:
            raise CouponError(f"{self.code}: duration must be one of {DURATIONS}")
        if (self.duration == "repeating") != (self.duration_periods is not None):
            raise CouponError(f"{self.code}: duration_periods is required for repeating only")
        if self.duration_periods is not None and self.duration_periods < 1:
            raise CouponError(f"{self.code}: duration_periods must be at least 1")


@dataclass
class Redemption:
    coupon: Coupon
    #: index of the billing period in which the coupon was redeemed
    first_period: int

    @property
    def last_period(self) -> int | None:
        """Index of the last discounted period (None: never ends)."""
        if self.coupon.duration == "forever":
            return None
        if self.coupon.duration == "once":
            return self.first_period
        return self.first_period + self.coupon.duration_periods - 1

    def applies_to(self, period_index: int) -> bool:
        """Whether an invoice for period ``period_index`` gets this coupon's discount."""
        if period_index < self.first_period:
            return False
        last = self.last_period
        return last is None or period_index <= last


def discount_amounts(coupons: Sequence[Coupon], amounts: Sequence[Money]) -> list[Money]:
    """The discount on each of ``amounts`` (one per line, zero for lines not discounted).

    Percent-off coupons apply first, each to what is left of every line, rounded per line.
    Amount-off coupons then take their amount from what is left, spread across the lines in
    proportion to it (``Money.allocate``); a line is never discounted below zero, and an
    amount-off coupon larger than what is left discounts only what is left.
    """
    if not amounts:
        return []
    currency = amounts[0].currency
    remaining = [a.rounded() for a in amounts]
    if any(r.is_negative() for r in remaining):
        raise CouponError("discounts apply to charges, not to credits")
    discounts = [Money.zero(currency) for _ in amounts]
    for coupon in (c for c in coupons if c.percent_off is not None):
        for i, left in enumerate(remaining):
            cut = (left * (coupon.percent_off / 100)).rounded()
            discounts[i] = discounts[i] + cut
            remaining[i] = left - cut
    for coupon in (c for c in coupons if c.amount_off is not None):
        if coupon.amount_off.currency != currency:
            raise CouponError(f"{coupon.code}: coupon is in {coupon.amount_off.currency}")
        left_total = Money.total(remaining, currency)
        if left_total.is_zero():
            break
        take = min(coupon.amount_off.rounded(), left_total)
        for i, part in enumerate(take.allocate([r.minor for r in remaining])):
            discounts[i] = discounts[i] + part
            remaining[i] = remaining[i] - part
    return discounts
