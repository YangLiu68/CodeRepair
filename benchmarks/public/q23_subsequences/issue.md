# `subsequences` returns wrong results for some inputs

`subsequences` in `algo/subsequences.py` does not do what its docstring specifies for every input.

- `subsequences(1, 5, 3)` returns `[]`; expected `[[1, 2, 3], [1, 2, 4], [1, 3, 4], [2, 3, 4]]`.

algo 0.1.0, Python 3.12
