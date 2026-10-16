# `pascal` returns wrong results for some inputs

`pascal` in `algo/pascal.py` does not do what its docstring specifies for every input.

- `pascal(2)` returns `[[1], [1]]`; expected `[[1], [1, 1]]`.

The failing test `tests/test_pascal.py::test_pascal[case1]` reproduces it.

algo 0.1.0, Python 3.12
