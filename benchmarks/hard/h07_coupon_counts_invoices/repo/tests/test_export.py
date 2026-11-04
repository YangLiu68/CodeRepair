import csv
import io
from datetime import datetime, timezone

from billing.export import HEADER, export_csv
from billing.invoice import Invoice, InvoiceLine
from billing.money import Money


def usd(text):
    return Money.of(text, "USD")


def rows(text):
    return list(csv.reader(io.StringIO(text)))


def invoice(customer, *lines):
    inv = Invoice(customer, "USD")
    inv.add_lines(list(lines))
    return inv.finalize("INV-2027-00001", datetime(2027, 6, 1, 9, tzinfo=timezone.utc))


def test_header_and_one_row_per_line():
    text = export_csv(
        [invoice("cus_1", InvoiceLine("Seats", usd("60.00"), quantity=5), InvoiceLine("Support", usd("30")))],
        {"cus_1": "Acme, Inc."},
    )
    parsed = rows(text)
    assert tuple(parsed[0]) == HEADER
    assert parsed[1] == ["INV-2027-00001", "2027-06-01", "Acme, Inc.", "Seats", "5", "60.00", "USD"]
    assert parsed[2][3:6] == ["Support", "1", "30.00"]


def test_credits_stay_numeric():
    text = export_csv([invoice("cus_1", InvoiceLine("Refund", usd("-12.50"), kind="credit"))])
    assert rows(text)[1][5] == "-12.50"


def test_formula_in_a_customer_name_is_neutralised():
    text = export_csv([invoice("cus_1", InvoiceLine("Seats", usd("1")))], {"cus_1": "=1+1"})
    assert rows(text)[1][2] == "'=1+1"


def test_drafts_are_not_exported():
    draft = Invoice("cus_1", "USD")
    draft.add_line(InvoiceLine("Seats", usd("1")))
    assert len(rows(export_csv([draft]))) == 1
