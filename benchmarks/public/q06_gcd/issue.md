# `gcd` returns wrong results for some inputs

`gcd` in `algo/gcd.py` does not do what its docstring specifies for every input.

- `gcd(13, 13)` raises `RecursionError`; expected `13`.
- `gcd(37, 600)` raises `RecursionError`; expected `1`.

The failing test `tests/test_gcd.py::test_gcd[case1]` reproduces it.

algo 0.1.0, Python 3.12
