# `lcs_length` returns wrong results for some inputs

`lcs_length` in `algo/lcs_length.py` does not do what its docstring specifies for every input.

- `lcs_length("witch", "sandwich")` returns `1`; expected `2`.

algo 0.1.0, Python 3.12
