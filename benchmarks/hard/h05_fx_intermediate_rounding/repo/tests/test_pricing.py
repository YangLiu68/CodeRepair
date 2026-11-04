import pytest

from billing.errors import PricingError
from billing.money import Money
from billing.plans import Price, Tier, price_from_row
from billing.pricing import amount_for, effective_unit_price


def usd(text):
    return Money.of(text, "USD")


GRADUATED = Price(
    "graduated",
    "USD",
    tiers=(Tier(100, usd("0.10")), Tier(1000, usd("0.09")), Tier(None, usd("0.08"))),
)
VOLUME = Price(
    "volume", "USD", tiers=(Tier(10, usd("12.00")), Tier(50, usd("10.00")), Tier(None, usd("8.00")))
)


def test_flat_and_per_unit():
    assert amount_for(Price("flat", "USD", unit_amount=usd("49.00")), 7) == usd("49.00")
    assert amount_for(Price("per_unit", "USD", unit_amount=usd("12.00")), 7) == usd("84.00")


def test_graduated_charges_each_unit_in_its_own_tier():
    assert amount_for(GRADUATED, 0) == usd("0.00")
    assert amount_for(GRADUATED, 150) == usd("14.50")
    assert amount_for(GRADUATED, 1000) == usd("91.00")
    assert amount_for(GRADUATED, 1001) == usd("91.08")


def test_volume_charges_every_unit_at_one_tier_price():
    assert amount_for(VOLUME, 5) == usd("60.00")
    assert amount_for(VOLUME, 20) == usd("200.00")
    assert amount_for(VOLUME, 60) == usd("480.00")
    assert amount_for(VOLUME, 0) == usd("0.00")


def test_volume_flat_fee():
    price = Price("volume", "USD", tiers=(Tier(5, usd("0"), usd("25.00")), Tier(None, usd("4.00"))))
    assert amount_for(price, 3) == usd("25.00")
    assert amount_for(price, 9) == usd("36.00")


def test_effective_unit_price():
    assert effective_unit_price(GRADUATED, 150) == usd("0.10")
    assert effective_unit_price(VOLUME, 0) == usd("12.00")


def test_price_validation():
    with pytest.raises(PricingError):
        Price("volume", "USD", tiers=(Tier(10, usd("1")),))
    with pytest.raises(PricingError):
        Price("volume", "USD", tiers=(Tier(10, usd("1")), Tier(5, usd("1")), Tier(None, usd("1"))))
    with pytest.raises(PricingError):
        Price("per_unit", "USD", unit_amount=Money.of("1", "EUR"))
    with pytest.raises(PricingError):
        amount_for(VOLUME, -1)


def test_price_from_row():
    assert price_from_row({"kind": "per_unit", "amount": "$12.00"}, "USD") == Price(
        "per_unit", "USD", unit_amount=usd("12.00")
    )
    tiered = price_from_row({"kind": "graduated", "tiers": "100:0.10; 1,000:0.09; *:0.08"}, "USD")
    assert tiered == GRADUATED
