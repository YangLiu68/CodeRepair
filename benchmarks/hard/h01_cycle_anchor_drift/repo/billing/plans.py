"""Plans, their priced components and the plan catalog.

A plan has one or more components. Each component has a ``Price``:

* ``flat``: a fixed amount per period, whatever the quantity;
* ``per_unit``: ``unit_amount`` times the quantity;
* ``volume``: every unit is charged at the price of the tier the *total* quantity falls in;
* ``graduated``: each unit is charged at the price of the tier that unit falls in.

Tier tables list tiers in ascending order. A tier's ``up_to`` is inclusive: with tiers
``up_to=10`` and ``up_to=50``, a quantity of exactly 10 is in the first tier and 11 in the
second. The last tier is open-ended (``up_to=None``). The arithmetic is in ``billing.pricing``.

Licensed components (seats) are billed in advance for the coming period; metered components
(API calls) are billed in arrears from recorded usage (``billing.usage``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .errors import PricingError
from .formatting import parse_amount
from .money import Money

PRICE_KINDS = ("flat", "per_unit", "volume", "graduated")


@dataclass(frozen=True)
class Tier:
    up_to: int | None
    unit_amount: Money
    #: charged once when the quantity reaches this tier (volume) or enters it (graduated)
    flat_amount: Money | None = None


@dataclass(frozen=True)
class Price:
    kind: str
    currency: str
    unit_amount: Money | None = None
    tiers: tuple[Tier, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in PRICE_KINDS:
            raise PricingError(f"unknown price kind {self.kind!r}")
        if self.kind in ("flat", "per_unit"):
            if self.unit_amount is None or self.tiers:
                raise PricingError(f"a {self.kind} price has a unit_amount and no tiers")
            if self.unit_amount.currency != self.currency:
                raise PricingError("unit_amount currency differs from the price currency")
            return
        if not self.tiers:
            raise PricingError(f"a {self.kind} price needs tiers")
        bounds = [t.up_to for t in self.tiers]
        if bounds[-1] is not None or any(b is None for b in bounds[:-1]):
            raise PricingError("only the last tier is open-ended")
        finite = [b for b in bounds if b is not None]
        if finite != sorted(set(finite)) or (finite and finite[0] < 1):
            raise PricingError("tier bounds must be positive and strictly increasing")
        for tier in self.tiers:
            amounts = [tier.unit_amount] + ([tier.flat_amount] if tier.flat_amount else [])
            if any(a.currency != self.currency for a in amounts):
                raise PricingError("tier currency differs from the price currency")


@dataclass(frozen=True)
class Component:
    code: str
    description: str
    price: Price
    metered: bool = False


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    currency: str
    components: tuple[Component, ...]
    interval_months: int = 1
    trial_days: int = 0

    def __post_init__(self) -> None:
        codes = [c.code for c in self.components]
        if len(codes) != len(set(codes)):
            raise PricingError(f"plan {self.code}: duplicate component codes")
        if any(c.price.currency != self.currency for c in self.components):
            raise PricingError(f"plan {self.code}: component currency differs from the plan")

    def component(self, code: str) -> Component:
        for component in self.components:
            if component.code == code:
                return component
        raise KeyError(f"plan {self.code} has no component {code!r}")

    @property
    def licensed(self) -> tuple[Component, ...]:
        return tuple(c for c in self.components if not c.metered)

    @property
    def metered(self) -> tuple[Component, ...]:
        return tuple(c for c in self.components if c.metered)


class Catalog:
    def __init__(self, plans: Iterable[Plan] = ()) -> None:
        self._plans: dict[str, Plan] = {}
        for plan in plans:
            self.add(plan)

    def add(self, plan: Plan) -> None:
        if plan.code in self._plans:
            raise PricingError(f"duplicate plan {plan.code}")
        self._plans[plan.code] = plan

    def get(self, code: str) -> Plan:
        try:
            return self._plans[code]
        except KeyError:
            raise KeyError(f"unknown plan {code!r}") from None

    def __iter__(self):
        return iter(self._plans.values())

    def __len__(self) -> int:
        return len(self._plans)


def price_from_row(row: Mapping[str, str], currency: str) -> Price:
    """A ``Price`` from a price-list row such as ``{"kind": "per_unit", "amount": "12.00"}``.

    Tiered rows give ``tiers`` as ``"10:12.00;50:10.00;*:8.00"`` (``*`` is open-ended).
    """
    kind = row["kind"]
    if kind in ("flat", "per_unit"):
        return Price(kind, currency, unit_amount=parse_amount(row["amount"], currency))
    tiers = []
    for chunk in row["tiers"].split(";"):
        bound, _, amount = chunk.strip().partition(":")
        bound = bound.strip()
        up_to = None if bound == "*" else int(bound.replace(",", "").replace("_", ""))
        tiers.append(Tier(up_to, parse_amount(amount, currency)))
    return Price(kind, currency, tiers=tuple(tiers))
