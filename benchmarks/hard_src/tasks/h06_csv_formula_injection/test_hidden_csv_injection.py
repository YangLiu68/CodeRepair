import csv
import io
from datetime import datetime, timezone

from billing.export import export_csv
from billing.invoice import Invoice, InvoiceLine
from billing.money import Money


def usd(text):
    return Money.of(text, "USD")


def exported(customer_name, *lines):
    invoice = Invoice("cus_1", "USD")
    invoice.add_lines(list(lines) or [InvoiceLine("Seats", usd("10"))])
    invoice.finalize("INV-2027-00042", datetime(2027, 6, 1, tzinfo=timezone.utc))
    return list(csv.reader(io.StringIO(export_csv([invoice], {"cus_1": customer_name}))))[1:]


def test_hidden_every_formula_trigger_is_neutralised_in_names():
    for payload in ("=1+1", "+1+1", "-2+3", "@SUM(1+9)*cmd|' /C calc'!A0", "\t=1+1", "\r=1+1"):
        (row,) = exported(payload)
        assert row[2] == "'" + payload, payload


def test_hidden_descriptions_are_neutralised():
    rows = exported(
        "Acme",
        InvoiceLine("-1 seat (downgrade)", usd("-12.00"), kind="credit"),
        InvoiceLine('=HYPERLINK("http://example.test","x")', usd("1.00")),
        InvoiceLine("+ add-on", usd("2.00")),
    )
    assert [r[3] for r in rows] == [
        "'-1 seat (downgrade)",
        '\'=HYPERLINK("http://example.test","x")',
        "'+ add-on",
    ]


def test_hidden_numbers_are_never_altered():
    rows = exported(
        "Acme",
        InvoiceLine("Refund", usd("-12.50"), quantity=-1, kind="credit"),
        InvoiceLine("Rounding", usd("-0.01"), kind="credit"),
        InvoiceLine("Seats", usd("60.00"), quantity=5),
    )
    assert [(r[4], r[5]) for r in rows] == [("-1", "-12.50"), ("1", "-0.01"), ("5", "60.00")]
    assert [r[0] for r in rows] == ["INV-2027-00042"] * 3


def test_hidden_formulas_inside_text_are_left_alone():
    (row,) = exported("Acme =1+1 Ltd")
    assert row[2] == "Acme =1+1 Ltd"
