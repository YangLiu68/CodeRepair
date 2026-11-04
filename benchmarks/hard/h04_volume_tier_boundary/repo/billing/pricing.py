"""Turning a quantity into an amount for a ``Price`` (see ``billing.plans`` for the rules)."""

from __future__ import annotations

from collections.abc import Sequence

from .errors import PricingError
from .money import Money
from .plans import Price, Tier


def tier_for(tiers: Sequence[Tier], quantity: int) -> Tier:
    """The tier a total ``quantity`` falls in (``up_to`` is inclusive)."""
    for tier in tiers:
        if tier.up_to is None or quantity < tier.up_to:
            return tier
    raise PricingError("tier table has no open-ended last tier")  # pragma: no cover


def volume_amount(tiers: Sequence[Tier], quantity: int, currency: str) -> Money:
    """All units at the unit price of the tier the total quantity falls in."""
    if quantity == 0:
        return Money.zero(currency)
    tier = tier_for(tiers, quantity)
    amount = tier.unit_amount * quantity
    if tier.flat_amount is not None:
        amount = amount + tier.flat_amount
    return amount.rounded()


def graduated_amount(tiers: Sequence[Tier], quantity: int, currency: str) -> Money:
    """Each unit at the unit price of the tier it falls in; tier flat fees once per tier used."""
    total = Money.zero(currency)
    lower = 0  # units already charged by earlier tiers
    for tier in tiers:
        if quantity <= lower:
            break
        upper = quantity if tier.up_to is None else min(quantity, tier.up_to)
        units = upper - lower
        total = total + tier.unit_amount * units
        if tier.flat_amount is not None:
            total = total + tier.flat_amount
        lower = upper
    return total.rounded()


def amount_for(price: Price, quantity: int) -> Money:
    """What ``quantity`` units cost under ``price`` for one period."""
    if quantity < 0:
        raise PricingError("quantity cannot be negative")
    if price.kind == "flat":
        return price.unit_amount.rounded()
    if price.kind == "per_unit":
        return (price.unit_amount * quantity).rounded()
    if price.kind == "volume":
        return volume_amount(price.tiers, quantity, price.currency)
    return graduated_amount(price.tiers, quantity, price.currency)


def effective_unit_price(price: Price, quantity: int) -> Money:
    """Average price per unit (for display); zero quantity gives the first tier's price."""
    if quantity == 0:
        return (price.unit_amount or price.tiers[0].unit_amount).rounded()
    total = amount_for(price, quantity)
    return Money(total.amount / quantity, total.currency).rounded()
