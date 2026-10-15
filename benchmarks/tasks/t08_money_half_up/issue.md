# Invoice totals are sometimes one cent short

Line items such as `1.005` are stored as 100 cents instead of 101. Our accounting rules
require half-up rounding, which is also what the `to_cents` docstring promises.

Failing test: `tests/test_money.py::test_to_cents_rounds_half_up`.
