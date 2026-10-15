"""Invoices made of described line amounts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from .money import format_cents, to_cents


@dataclass
class Invoice:
    lines: List[Tuple[str, int]] = field(default_factory=list)

    def add_line(self, description: str, amount: str) -> None:
        self.lines.append((description, to_cents(amount)))

    def total_cents(self) -> int:
        return sum(cents for _, cents in self.lines)

    def render(self) -> str:
        rows = [f"{desc:<20}{format_cents(cents):>10}" for desc, cents in self.lines]
        rows.append(f"{'TOTAL':<20}{format_cents(self.total_cents()):>10}")
        return "\n".join(rows)
