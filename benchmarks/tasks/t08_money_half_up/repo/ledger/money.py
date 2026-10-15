"""Money helpers. Amounts are stored as integer cents."""
from __future__ import annotations

from typing import List


def to_cents(amount: str) -> int:
    """Convert a decimal string such as ``"12.345"`` to cents, rounding half up."""
    return round(float(amount) * 100)


def split_evenly(total_cents: int, ways: int) -> List[int]:
    """Split ``total_cents`` into ``ways`` parts that differ by at most one cent."""
    if ways < 1:
        raise ValueError("ways must be at least 1")
    base, remainder = divmod(total_cents, ways)
    return [base + 1 if i < remainder else base for i in range(ways)]


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"
