# `get_factors` returns wrong results for some inputs

`get_factors` in `algo/get_factors.py` does not do what its docstring specifies for every input.

- `get_factors(100)` returns `[2, 2, 5]`; expected `[2, 2, 5, 5]`.

algo 0.1.0, Python 3.12
