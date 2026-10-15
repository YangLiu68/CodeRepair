# `find_in_sorted` returns wrong results for some inputs

`find_in_sorted` in `algo/find_in_sorted.py` does not do what its docstring specifies for every input.

- `find_in_sorted([1, 2, 3, 4, 6, 7, 8], 5)` raises `RecursionError`; expected `-1`.

The failing test `tests/test_find_in_sorted.py::test_find_in_sorted[case1]` reproduces it.

algo 0.1.0, Python 3.12
