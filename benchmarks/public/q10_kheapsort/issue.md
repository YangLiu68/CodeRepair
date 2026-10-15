# `kheapsort` returns wrong results for some inputs

`kheapsort` in `algo/kheapsort.py` does not do what its docstring specifies for every input.

- `kheapsort([3, 2, 1, 5, 4], 2)` returns `[2, 2, 1, 3, 3, 4, 5]`; expected `[1, 2, 3, 4, 5]`.
- `kheapsort([5, 4, 3, 2, 1], 4)` returns `[2, 3, 3, 2, 1, 4, 4, 5, 5]`; expected `[1, 2, 3, 4, 5]`.

The failing test `tests/test_kheapsort.py::test_kheapsort[case1]` reproduces it.

algo 0.1.0, Python 3.12
