# `lcs_length` returns wrong results for some inputs

`lcs_length` in `algo/lcs_length.py` does not do what its docstring specifies for every input.

- `lcs_length("witch", "sandwich")` returns `1`; expected `2`.
- `lcs_length("meow", "homeowner")` returns `1`; expected `4`.

The failing test `tests/test_lcs_length.py::test_lcs_length[case0]` reproduces it.

algo 0.1.0, Python 3.12
