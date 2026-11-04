"""Parsing and displaying money amounts.

``parse_amount`` reads amounts written by people and spreadsheets: an optional currency symbol
or code, an optional sign, digits with optional thousands separators (``,`` or ``'`` or a
space) and a ``.`` decimal point. Comma decimal separators ("12,50") are not accepted, since
"1,250" would be ambiguous; ask for "1250" or "12.50" instead.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .currency import get_currency
from .money import Money

_AMOUNT_RE = re.compile(
    r"""^\s*
    (?P<sign>[-+])?\s*
    (?P<int>\d{1,3}(?:[,' ]\d{3})+|\d+)
    (?:\.(?P<frac>\d+))?
    \s*$""",
    re.VERBOSE,
)


def parse_amount(text: str, currency: str) -> Money:
    """``parse_amount("$1,234.50", "USD")`` is 1234.50 USD. Raises ``ValueError`` if malformed."""
    cleaned = text.strip()
    info = get_currency(currency)
    for marker in (info.symbol.strip(), currency):
        if marker and cleaned.upper().startswith(marker.upper()):
            cleaned = cleaned[len(marker) :]
        if marker and cleaned.upper().endswith(marker.upper()):
            cleaned = cleaned[: -len(marker)]
    match = _AMOUNT_RE.match(cleaned)
    if match is None:
        raise ValueError(f"not an amount: {text!r}")
    digits = re.sub(r"[,' ]", "", match["int"])
    if match["frac"]:
        if len(match["frac"]) > info.minor_units:
            raise ValueError(f"{text!r} has more decimals than {currency} allows")
        digits += "." + match["frac"]
    try:
        value = Decimal(digits)
    except InvalidOperation as exc:  # pragma: no cover - the regex only lets digits through
        raise ValueError(f"not an amount: {text!r}") from exc
    if match["sign"] == "-":
        value = -value
    return Money.of(value, currency)


def format_money(money: Money, *, accounting: bool = False) -> str:
    """``$1,234.50``, ``-$12.50`` (``($12.50)`` with ``accounting=True``), ``1 250,00 kr``."""
    info = get_currency(money.currency)
    rounded = money.rounded()
    magnitude = abs(rounded.amount)
    whole, _, frac = f"{magnitude:f}".partition(".")
    grouped = f"{int(whole):,}"
    if info.code == "SEK":
        grouped = grouped.replace(",", " ")
        number = grouped + ("," + frac if frac else "")
    else:
        number = grouped + ("." + frac if frac else "")
    text = info.symbol + number if info.symbol_first else number + info.symbol
    if rounded.is_negative():
        return f"({text})" if accounting else "-" + text
    return text
