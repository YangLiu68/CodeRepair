# `find_first_in_sorted` returns wrong results for some inputs

`find_first_in_sorted` in `algo/find_first_in_sorted.py` does not do what its docstring specifies for every input.

- `find_first_in_sorted([3, 4, 5, 5, 5, 5, 6], 7)` raises `IndexError`; expected `-1`.
- `find_first_in_sorted([3, 4, 5, 5, 5, 5, 6], 2)` does not return (it runs for more than 2 seconds); expected `-1`.

algo 0.1.0, Python 3.12
