"""CSV export of invoice lines for finance teams and spreadsheets.

One row per invoice line: ``number, issued, customer, description, quantity, amount,
currency``. ``quantity`` and ``amount`` are numeric columns, written as plain numbers
(``-12.50`` for a credit) so spreadsheets can sum them.

Text columns hold customer-controlled data (customer names, plan and coupon descriptions),
so they are neutralised against spreadsheet formula injection (CSV injection, CWE-1236): a
text value that starts with ``=``, ``+``, ``-``, ``@``, a tab or a carriage return is written
with a leading apostrophe, which spreadsheets show as text instead of evaluating it. Numeric
columns are never altered.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping

from .invoice import Invoice

HEADER = ("number", "issued", "customer", "description", "quantity", "amount", "currency")
FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def neutralize(text: str) -> str:
    """A text cell that spreadsheets will not evaluate."""
    return "'" + text if text.startswith(FORMULA_TRIGGERS) else text


def invoice_rows(
    invoices: Iterable[Invoice], customer_names: Mapping[str, str] | None = None
) -> list[list[str]]:
    names = customer_names or {}
    rows = []
    for invoice in invoices:
        if invoice.number is None:
            continue  # drafts are not exported
        issued = invoice.issued_at.date().isoformat() if invoice.issued_at else ""
        customer = names.get(invoice.customer_id, invoice.customer_id)
        for line in invoice.lines:
            rows.append(
                [
                    neutralize(invoice.number),
                    issued,
                    neutralize(customer),
                    neutralize(line.description),
                    str(line.quantity),
                    str(line.amount.rounded().amount),
                    invoice.currency,
                ]
            )
    return rows


def export_csv(
    invoices: Iterable[Invoice], customer_names: Mapping[str, str] | None = None
) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(HEADER)
    writer.writerows(invoice_rows(invoices, customer_names))
    return buffer.getvalue()
