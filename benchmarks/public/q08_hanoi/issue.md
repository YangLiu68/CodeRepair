# `hanoi` returns wrong results for some inputs

`hanoi` in `algo/hanoi.py` does not do what its docstring specifies for every input.

- `hanoi(1, 1, 3)` returns `[(1, 2)]`; expected `[[1, 3]]`.

The failing test `tests/test_hanoi.py::test_hanoi[case1]` reproduces it.

algo 0.1.0, Python 3.12
