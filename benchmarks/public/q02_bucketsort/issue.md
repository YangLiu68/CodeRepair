# `bucketsort` returns wrong results for some inputs

`bucketsort` in `algo/bucketsort.py` does not do what its docstring specifies for every input.

- `bucketsort([3, 11, 2, 9, 1, 5], 12)` returns `[0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3, 3, 4, 5, 5, 5, 5, 5]`; expected `[1, 2, 3, 5, 9, 11]`.

The failing test `tests/test_bucketsort.py::test_bucketsort[case1]` reproduces it.

algo 0.1.0, Python 3.12
