"""Currency metadata: ISO codes, minor units and display symbols.

The registry is deliberately small and explicit. ``minor_units`` is the number of
decimal places an amount in that currency is rounded to: 2 for USD and EUR, 0 for
JPY, 3 for KWD. Every rounded ``Money`` amount is a whole number of minor units.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .errors import UnknownCurrency


@dataclass(frozen=True)
class Currency:
    code: str
    minor_units: int
    symbol: str
    #: symbol written before the amount ("$12.50") or after it ("12,50 kr")
    symbol_first: bool = True

    @property
    def quantum(self) -> Decimal:
        """The smallest representable amount, e.g. ``Decimal("0.01")``."""
        return Decimal(1).scaleb(-self.minor_units)


_REGISTRY: dict[str, Currency] = {
    c.code: c
    for c in (
        Currency("USD", 2, "$"),
        Currency("EUR", 2, "€"),
        Currency("GBP", 2, "£"),
        Currency("CHF", 2, "CHF "),
        Currency("SEK", 2, " kr", symbol_first=False),
        Currency("JPY", 0, "¥"),
        Currency("KWD", 3, "KD "),
        Currency("IDR", 2, "Rp"),
    )
}


def get_currency(code: str) -> Currency:
    try:
        return _REGISTRY[code]
    except KeyError:
        raise UnknownCurrency(f"unknown currency {code!r}") from None


def register_currency(currency: Currency) -> None:
    """Add a currency (or replace one with the same code)."""
    if len(currency.code) != 3 or not currency.code.isupper():
        raise ValueError(f"currency codes are three upper-case letters, got {currency.code!r}")
    if not 0 <= currency.minor_units <= 4:
        raise ValueError("minor_units must be between 0 and 4")
    _REGISTRY[currency.code] = currency


def known_currencies() -> list[str]:
    return sorted(_REGISTRY)


def quantum(code: str) -> Decimal:
    return get_currency(code).quantum
