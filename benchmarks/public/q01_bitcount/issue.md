# `bitcount` returns wrong results for some inputs

`bitcount` in `algo/bitcount.py` does not do what its docstring specifies for every input.

- `bitcount(127)` does not return (it runs for more than 2 seconds); expected `7`.

The failing test `tests/test_bitcount.py::test_bitcount[case0]` reproduces it.

algo 0.1.0, Python 3.12
