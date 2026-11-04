"""Sales tax and VAT.

A ``TaxRate`` is a percentage for a jurisdiction, and either *exclusive* (tax is added on top
of the price, like US sales tax) or *inclusive* (the price already contains the tax, like
EU VAT on consumer prices).

* Exclusive: the tax on a net amount N at rate r is ``N * r``.
* Inclusive: the tax contained in a gross amount G at rate r is ``G * r / (1 + r)``.

Tax is always computed per invoice line, on the amount the customer actually pays for that
line, that is after discounts, and each line's tax is rounded to the currency's minor units.
The invoice's tax is the sum of the rounded line taxes. See ``billing.invoice``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .money import Money


@dataclass(frozen=True)
class TaxRate:
    jurisdiction: str
    percent: Decimal
    inclusive: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.percent, Decimal):
            object.__setattr__(self, "percent", Decimal(str(self.percent)))
        if not 0 <= self.percent < 100:
            raise ValueError(f"tax percent must be in [0, 100), got {self.percent}")

    @property
    def fraction(self) -> Decimal:
        return self.percent / 100

    @property
    def is_zero(self) -> bool:
        return self.percent == 0


NO_TAX = TaxRate("none", Decimal(0))


def tax_on_net(net: Money, rate: TaxRate) -> Money:
    """Exclusive tax on ``net``, rounded."""
    return (net * rate.fraction).rounded()


def tax_in_gross(gross: Money, rate: TaxRate) -> Money:
    """The tax contained in an inclusive ``gross`` amount, rounded."""
    return (gross * (rate.fraction / (1 + rate.fraction))).rounded()


def line_tax(amount: Money, rate: TaxRate) -> Money:
    """Tax for one line whose payable amount (after discounts) is ``amount``."""
    if rate.is_zero:
        return Money.zero(amount.currency)
    return tax_in_gross(amount, rate) if rate.inclusive else tax_on_net(amount, rate)


@dataclass
class TaxTable:
    """Rates by jurisdiction, with per-customer exemptions (e.g. resellers, charities)."""

    rates: dict[str, TaxRate] = field(default_factory=dict)
    exempt_customers: set[str] = field(default_factory=set)

    def add(self, rate: TaxRate) -> None:
        self.rates[rate.jurisdiction] = rate

    def exempt(self, customer_id: str) -> None:
        self.exempt_customers.add(customer_id)

    def rate_for(self, jurisdiction: str, customer_id: str | None = None) -> TaxRate:
        """The rate that applies to a customer in ``jurisdiction``.

        An exempt customer pays no tax, but an inclusive price stays inclusive: the zero rate
        keeps the jurisdiction's ``inclusive`` flag, so the price the customer sees is unchanged.
        """
        rate = self.rates.get(jurisdiction)
        if rate is None:
            raise KeyError(f"no tax rate for jurisdiction {jurisdiction!r}")
        if customer_id is not None and customer_id in self.exempt_customers:
            return TaxRate(rate.jurisdiction, Decimal(0), rate.inclusive)
        return rate
