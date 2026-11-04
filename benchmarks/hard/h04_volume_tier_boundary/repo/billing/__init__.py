"""billing: subscription billing with exact money arithmetic.

Modules, roughly in dependency order:

* ``currency``, ``money``, ``formatting``, ``fx``: amounts, rounding, parsing, conversion
* ``dates``, ``periods``: half-open periods and billing cycles anchored to a day of the month
* ``plans``, ``pricing``, ``usage``: price lists, tiered pricing, metered usage
* ``tax``, ``discounts``, ``invoice``, ``proration``: invoice lines and totals
* ``subscriptions``, ``dunning``, ``payments``: the subscription lifecycle and collection
* ``ledger``, ``export``, ``ids``, ``events``: bookkeeping, CSV export, numbering, events
"""

from .errors import BillingError
from .money import Money

__version__ = "0.4.2"
__all__ = ["BillingError", "Money", "__version__"]
