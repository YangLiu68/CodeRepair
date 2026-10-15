from ledger.invoice import Invoice


def test_total_and_render():
    invoice = Invoice()
    invoice.add_line("Consulting", "150.00")
    invoice.add_line("Travel", "42.50")
    assert invoice.total_cents() == 19250
    assert invoice.render().splitlines()[-1].endswith("192.50")
