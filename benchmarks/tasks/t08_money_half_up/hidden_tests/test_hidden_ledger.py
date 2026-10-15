from ledger.invoice import Invoice
from ledger.money import to_cents


def test_hidden_half_up_not_bankers_rounding():
    assert to_cents("0.125") == 13
    assert to_cents("0.135") == 14


def test_hidden_no_binary_float_artifacts():
    assert to_cents("2.675") == 268
    assert to_cents("1.015") == 102


def test_hidden_invoice_total_uses_half_up():
    invoice = Invoice()
    invoice.add_line("a", "1.005")
    invoice.add_line("b", "1.005")
    assert invoice.total_cents() == 202


def test_hidden_exact_cent_values_are_unchanged():
    # Added 2026-10-14 after the M1 smoke run: an incorrect "+ 0.5" patch passed every
    # other test. Exact cent amounts must convert without any rounding bias.
    for amount, cents in (("0.01", 1), ("0.07", 7), ("10.01", 1001), ("123.45", 12345)):
        assert to_cents(amount) == cents
