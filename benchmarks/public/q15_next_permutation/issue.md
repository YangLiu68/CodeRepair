# `next_permutation` returns wrong results for some inputs

`next_permutation` in `algo/next_permutation.py` does not do what its docstring specifies for every input.

- `next_permutation([3, 2, 4, 1])` returns `[3, 1, 2, 4]`; expected `[3, 4, 1, 2]`.

The failing test `tests/test_next_permutation.py::test_next_permutation[case0]` reproduces it.

algo 0.1.0, Python 3.12
