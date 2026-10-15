# `flatten` returns wrong results for some inputs

`flatten` in `algo/flatten.py` does not do what its docstring specifies for every input.

- `flatten([[1, [], [2, 3]], [[4]], 5])` returns `[<generator object flatten at 0x103f34d60>, <generator object flatten at 0x103f34f20>, <generator object flatten at 0x103f35000>, <generator object flatten at 0x103f350e0>, <generator object flatten at 0x103f34c80>]`; expected `[1, 2, 3, 4, 5]`.

algo 0.1.0, Python 3.12
