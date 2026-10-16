# `flatten` returns wrong results for some inputs

`flatten` in `algo/flatten.py` does not do what its docstring specifies for every input.

- `flatten([[1, [], [2, 3]], [[4]], 5])` returns `[<generator object flatten at 0x...>, <generator object flatten at 0x...>, <generator object flatten at 0x...>, <generator object flatten at 0x...>, <generator object flatten at 0x...>]`; expected `[1, 2, 3, 4, 5]`.

algo 0.1.0, Python 3.12
