# `kth` returns wrong results for some inputs

`kth` in `algo/kth.py` does not do what its docstring specifies for every input.

- `kth([1, 2, 3, 4, 5, 6, 7], 4)` raises `IndexError`; expected `5`.
- `kth([3, 6, 7, 1, 6, 3, 8, 9], 5)` raises `IndexError`; expected `7`.

algo 0.1.0, Python 3.12
