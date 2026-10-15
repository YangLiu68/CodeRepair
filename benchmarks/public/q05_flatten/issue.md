# `flatten` returns wrong results for some inputs

`flatten` in `algo/flatten.py` does not do what its docstring specifies for every input.

- `flatten([[1, [], [2, 3]], [[4]], 5])` returns `[<generator object flatten at 0x1027e4d60>, <generator object flatten at 0x1027e4f20>, <generator object flatten at 0x1027e5000>, <generator object flatten at 0x1027e50e0>, <generator object flatten at 0x1027e4c80>]`; expected `[1, 2, 3, 4, 5]`.
- `flatten([[], [], 1, [], 1, [], []])` returns `[<generator object flatten at 0x1027e4e40>, <generator object flatten at 0x1027e4d60>]`; expected `[1, 1]`.

algo 0.1.0, Python 3.12
