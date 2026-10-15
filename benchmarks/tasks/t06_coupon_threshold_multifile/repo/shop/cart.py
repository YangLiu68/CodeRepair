"""Shopping cart."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .coupons import Coupon, lookup
from .pricing import apply_percent_discount


@dataclass
class LineItem:
    sku: str
    unit_cents: int
    quantity: int = 1

    @property
    def total_cents(self) -> int:
        return self.unit_cents * self.quantity


@dataclass
class Cart:
    items: List[LineItem] = field(default_factory=list)
    coupon: Optional[Coupon] = None

    def add(self, sku: str, unit_cents: int, quantity: int = 1) -> None:
        if quantity < 1:
            raise ValueError("quantity must be positive")
        self.items.append(LineItem(sku, unit_cents, quantity))

    def apply_coupon(self, code: str) -> None:
        self.coupon = lookup(code)

    def subtotal(self) -> int:
        return sum(item.total_cents for item in self.items)

    def total(self) -> int:
        subtotal = self.subtotal()
        if self.coupon and self.coupon.is_applicable(subtotal):
            return apply_percent_discount(subtotal, self.coupon.percent)
        return subtotal
