# `mergesort` returns wrong results for some inputs

`mergesort` in `algo/mergesort.py` does not do what its docstring specifies for every input.

- `mergesort([1, 2, 6, 72, 7, 33, 4])` raises `RecursionError`; expected `[1, 2, 4, 6, 7, 33, 72]`.

The failing test `tests/test_mergesort.py::test_mergesort[case1]` reproduces it.

algo 0.1.0, Python 3.12
