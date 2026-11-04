"""Exceptions raised by the billing library."""


class BillingError(Exception):
    """Base class for every error raised by this package."""


class UnknownCurrency(BillingError):
    """A currency code that is not in the registry."""


class CurrencyMismatch(BillingError):
    """Arithmetic or comparison between amounts in different currencies."""


class RateNotFound(BillingError):
    """No exchange rate is known for a currency pair."""


class InvalidPeriod(BillingError):
    """A period that ends before it starts, or a date outside a schedule."""


class InvalidTransition(BillingError):
    """A subscription operation that its current status does not allow."""


class CouponError(BillingError):
    """A coupon that is malformed or cannot be applied."""


class PricingError(BillingError):
    """A price or tier table that is malformed."""


class PaymentError(BillingError):
    """A payment that cannot be applied."""


class UnbalancedEntry(BillingError):
    """A journal entry whose debits and credits do not match."""
