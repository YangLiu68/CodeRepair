# `lis` returns wrong results for some inputs

`lis` in `algo/lis.py` does not do what its docstring specifies for every input.

- `lis([4, 1, 5, 3, 7, 6, 2])` returns `2`; expected `3`.

The failing test `tests/test_lis.py::test_lis[case8]` reproduces it.

algo 0.1.0, Python 3.12
