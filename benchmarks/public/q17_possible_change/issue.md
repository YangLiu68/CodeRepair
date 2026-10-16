# `possible_change` returns wrong results for some inputs

`possible_change` in `algo/possible_change.py` does not do what its docstring specifies for every input.

- `possible_change([1, 5, 10, 25], 11)` raises `ValueError`; expected `4`.

algo 0.1.0, Python 3.12
