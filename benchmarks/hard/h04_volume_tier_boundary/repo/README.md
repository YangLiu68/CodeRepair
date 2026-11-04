# billing

Subscription billing for a SaaS product: plans and price lists, invoices with coupons and tax,
mid-period plan changes, metered usage, payment retries, a double-entry ledger and CSV export.
Amounts are exact (`Decimal`); nothing in this package uses floats.

```python
from datetime import date
from billing.money import Money
from billing.plans import Component, Plan, Price
from billing.subscriptions import Subscription

seat = Price("per_unit", "USD", unit_amount=Money.of("12.00", "USD"))
team = Plan("team", "Team", "USD", (Component("seats", "Seats", seat),))
sub = Subscription.start("sub_1", "cus_1", team, date(2027, 1, 31), quantities={"seats": 5})
sub.invoices[0].total        # Money('60.00', 'USD')
sub.renew().period           # 2027-02-28..2027-03-31
```

## Conventions

- **Periods are half-open**: `[start, end)`. A period's end is the next period's start.
- **Billing cycles keep their anchor day**: a cycle anchored on the 31st bills on the 31st, or
  on the last day of shorter months, and returns to the 31st afterwards.
- **Rounding** is commercial (half away from zero) to the currency's minor units, and happens as
  late as possible: per invoice line for discounts and tax, once per conversion for FX.
- **Coupons last a number of billing periods**, not a number of invoices.
- **Tax is computed per line after discounts**, exclusive or inclusive (VAT) per jurisdiction.
- **Credits mirror charges**: a prorated credit is split across lines exactly like a charge of
  the same size, with the sign flipped.

## Development

```
python -m pytest
```
