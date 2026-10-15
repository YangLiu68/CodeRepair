"""Price arithmetic in integer cents."""
from __future__ import annotations


def apply_percent_discount(cents: int, percent: int) -> int:
    """Return ``cents`` reduced by ``percent`` (0-100); the discount is rounded down."""
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    return cents - cents * percent // 100


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"
