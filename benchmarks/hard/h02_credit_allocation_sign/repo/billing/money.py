"""Exact money arithmetic on ``Decimal`` amounts.

``Money`` keeps whatever precision arithmetic produces (``Money.of("10", "USD") * Decimal("0.19")``
is exactly 1.90, a third of a dollar keeps all its digits) until ``rounded()`` is called. Rounding
is commercial rounding, half away from zero (``ROUND_HALF_UP``), to the currency's minor units.

Amounts in different currencies never mix: adding, subtracting or comparing them raises
``CurrencyMismatch``. Convert first (``billing.fx``).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .currency import get_currency
from .errors import CurrencyMismatch

ROUNDING = ROUND_HALF_UP


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        get_currency(self.currency)  # validates the code
        if not isinstance(self.amount, Decimal):
            object.__setattr__(self, "amount", Decimal(str(self.amount)))

    # ------------------------------------------------------------------ construction

    @classmethod
    def of(cls, amount: str | int | Decimal, currency: str) -> Money:
        """A rounded amount: ``Money.of("19.999", "USD")`` is 20.00 USD."""
        if isinstance(amount, float):
            raise TypeError("use a str, int or Decimal for money, not float")
        return cls(Decimal(str(amount)), currency).rounded()

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(Decimal(0), currency).rounded()

    @classmethod
    def from_minor(cls, minor: int, currency: str) -> Money:
        """``Money.from_minor(1250, "USD")`` is 12.50 USD; for JPY it is 1250 JPY."""
        units = get_currency(currency).minor_units
        return cls(Decimal(minor).scaleb(-units), currency).rounded()

    @classmethod
    def total(cls, amounts: Iterable[Money], currency: str) -> Money:
        """Sum of ``amounts`` (zero in ``currency`` when empty)."""
        result = cls.zero(currency)
        for amount in amounts:
            result = result + amount
        return result

    # ------------------------------------------------------------------ rounding

    def rounded(self) -> Money:
        quantum = get_currency(self.currency).quantum
        return Money(self.amount.quantize(quantum, rounding=ROUNDING), self.currency)

    @property
    def minor(self) -> int:
        """The rounded amount in minor units (cents, fils, yen)."""
        units = get_currency(self.currency).minor_units
        return int(self.rounded().amount.scaleb(units))

    # ------------------------------------------------------------------ arithmetic

    def _check(self, other: object) -> Money:
        if not isinstance(other, Money):
            raise TypeError(f"expected Money, got {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatch(f"{self.currency} and {other.currency} do not mix")
        return other

    def __add__(self, other: Money) -> Money:
        other = self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        other = self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __abs__(self) -> Money:
        return Money(abs(self.amount), self.currency)

    def __mul__(self, factor: int | Decimal) -> Money:
        if isinstance(factor, float) or isinstance(factor, Money):
            raise TypeError("multiply money by an int or a Decimal")
        return Money(self.amount * Decimal(factor), self.currency)

    __rmul__ = __mul__

    def __lt__(self, other: Money) -> bool:
        return self.amount < self._check(other).amount

    def __le__(self, other: Money) -> bool:
        return self.amount <= self._check(other).amount

    def __gt__(self, other: Money) -> bool:
        return self.amount > self._check(other).amount

    def __ge__(self, other: Money) -> bool:
        return self.amount >= self._check(other).amount

    def is_zero(self) -> bool:
        return self.amount == 0

    def is_negative(self) -> bool:
        return self.amount < 0

    def clamp_min(self, floor: Money) -> Money:
        """This amount, or ``floor`` if this amount is smaller."""
        return floor if self < floor else self

    # ------------------------------------------------------------------ splitting

    def allocate(self, weights: Sequence[int | Decimal]) -> list[Money]:
        """Split into parts proportional to ``weights`` that add up exactly to this amount.

        Works on the rounded amount in minor units (largest-remainder method): every part
        gets the integer part of its exact share, and the minor units left over go one each
        to the parts with the largest fractional remainders, earlier parts first on ties.
        ``Money.of("10.00", "USD").allocate([1, 1, 1])`` is 3.34, 3.33, 3.33.

        A negative amount is split exactly like its absolute value, with every part negated:
        ``Money.of("-10.00", "USD").allocate([1, 1, 1])`` is -3.34, -3.33, -3.33. Credits
        therefore mirror the charges they reverse, line for line.
        """
        if not weights:
            raise ValueError("allocate needs at least one weight")
        weights = [Decimal(w) for w in weights]
        if any(w < 0 for w in weights) or sum(weights) <= 0:
            raise ValueError("weights must be non-negative and not all zero")
        total_weight = sum(weights)
        minor = self.minor
        shares = [minor * w / total_weight for w in weights]
        parts = [int(share) for share in shares]
        leftover = minor - sum(parts)
        by_remainder = sorted(range(len(shares)), key=lambda i: (-(shares[i] - parts[i]), i))
        for index in by_remainder[:leftover]:
            parts[index] += 1
        return [Money.from_minor(part, self.currency) for part in parts]

    def split(self, count: int) -> list[Money]:
        """``count`` equal parts that add up exactly (``allocate`` with equal weights)."""
        if count < 1:
            raise ValueError("count must be at least 1")
        return self.allocate([1] * count)

    # ------------------------------------------------------------------ display

    def __str__(self) -> str:
        return f"{self.rounded().amount} {self.currency}"

    def __repr__(self) -> str:
        return f"Money({str(self.amount)!r}, {self.currency!r})"
