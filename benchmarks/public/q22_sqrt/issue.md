# `sqrt` returns wrong results for some inputs

`sqrt` in `algo/sqrt.py` does not do what its docstring specifies for every input.

- `sqrt(2, 0.01)` does not return (it runs for more than 2 seconds); expected `1.4166666666666665`.

The failing test `tests/test_sqrt.py::test_sqrt[case0]` reproduces it.

algo 0.1.0, Python 3.12
