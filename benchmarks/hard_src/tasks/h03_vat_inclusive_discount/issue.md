# VAT on discounted invoices does not match our VAT return (Germany)

From our accountant in Berlin: on invoices with a coupon, the VAT we show is more than the VAT
contained in what the customer actually paid, so our VAT return and our invoices disagree.

Example: Pro plan at €119.00 including 19% VAT, with a 10% coupon. The customer pays €107.10
and the invoice says VAT €19.00. The VAT contained in €107.10 is €17.10.

Invoices without a coupon are correct, and so are US invoices (sales tax added on top).

`tests/test_invoice.py::test_inclusive_vat_is_computed_on_the_discounted_price` reproduces it.
