"""Exchange rates and currency conversion.

Rates are quoted against a base currency (USD unless configured otherwise):
``ExchangeRates(rates={"EUR": "0.92"})`` means one USD buys 0.92 EUR. Converting between two
non-base currencies uses the cross rate ``rate[target] / rate[source]``.

A rate set for an explicit pair with ``set_pair(source, target, rate)`` takes precedence over
the cross rate for that pair, and its inverse is used for the opposite direction.

``convert`` multiplies the amount by the exact rate and rounds once, to the target currency's
minor units (commercial rounding, see ``billing.money``). Nothing is rounded on the way: in
particular a cross conversion never rounds an intermediate amount in the base currency.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from .currency import get_currency
from .errors import RateNotFound
from .money import Money


class ExchangeRates:
    def __init__(
        self, base: str = "USD", rates: Mapping[str, str | int | Decimal] | None = None
    ) -> None:
        get_currency(base)
        self.base = base
        self._rates: dict[str, Decimal] = {base: Decimal(1)}
        self._pairs: dict[tuple[str, str], Decimal] = {}
        for code, rate in (rates or {}).items():
            self.set_rate(code, rate)

    @staticmethod
    def _positive(rate: str | int | Decimal) -> Decimal:
        if isinstance(rate, float):
            raise TypeError("give rates as str, int or Decimal, not float")
        value = Decimal(str(rate))
        if value <= 0:
            raise ValueError(f"rates must be positive, got {rate}")
        return value

    def set_rate(self, code: str, rate: str | int | Decimal) -> None:
        """Units of ``code`` that one unit of the base currency buys."""
        get_currency(code)
        if code == self.base:
            raise ValueError("the base currency's rate is always 1")
        self._rates[code] = self._positive(rate)

    def set_pair(self, source: str, target: str, rate: str | int | Decimal) -> None:
        """Units of ``target`` that one unit of ``source`` buys, overriding the cross rate."""
        get_currency(source)
        get_currency(target)
        if source == target:
            raise ValueError("a pair needs two different currencies")
        self._pairs[(source, target)] = self._positive(rate)

    def has_rate(self, code: str) -> bool:
        return code in self._rates

    def rate(self, source: str, target: str) -> Decimal:
        """Exact units of ``target`` per unit of ``source``."""
        if source == target:
            return Decimal(1)
        if (source, target) in self._pairs:
            return self._pairs[(source, target)]
        if (target, source) in self._pairs:
            return 1 / self._pairs[(target, source)]
        try:
            return self._rates[target] / self._rates[source]
        except KeyError as exc:
            raise RateNotFound(f"no rate for {exc.args[0]} (base {self.base})") from None

    def to_base(self, money: Money) -> Money:
        """``money`` in the base currency, rounded (for reports kept in the base currency)."""
        return self.convert(money, self.base)

    def convert(self, money: Money, target: str) -> Money:
        """``money`` in ``target``, rounded once to the target's minor units."""
        if money.currency == target:
            return money.rounded()
        return Money(money.amount * self.rate(money.currency, target), target).rounded()
