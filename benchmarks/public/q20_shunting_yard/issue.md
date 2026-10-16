# `shunting_yard` returns wrong results for some inputs

`shunting_yard` in `algo/shunting_yard.py` does not do what its docstring specifies for every input.

- `shunting_yard([10, "-", 5, "-", 2])` returns `[10, 5, 2]`; expected `[10, 5, "-", 2, "-"]`.

The failing test `tests/test_shunting_yard.py::test_shunting_yard[case2]` reproduces it.

algo 0.1.0, Python 3.12
