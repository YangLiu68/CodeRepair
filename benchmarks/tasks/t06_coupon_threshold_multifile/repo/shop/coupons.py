"""Coupon definitions and eligibility rules."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Coupon:
    code: str
    percent: int
    min_subtotal_cents: int = 0

    def is_applicable(self, subtotal_cents: int) -> bool:
        """A coupon applies once the subtotal reaches its minimum spend."""
        return subtotal_cents > self.min_subtotal_cents


COUPONS = {
    "SAVE10": Coupon("SAVE10", 10, min_subtotal_cents=5000),
    "WELCOME5": Coupon("WELCOME5", 5),
}


def lookup(code: str) -> Coupon:
    try:
        return COUPONS[code.strip().upper()]
    except KeyError:
        raise KeyError(f"unknown coupon {code!r}") from None
