# `to_base` returns wrong results for some inputs

`to_base` in `algo/to_base.py` does not do what its docstring specifies for every input.

- `to_base(31, 16)` returns `'F1'`; expected `"1F"`.

The failing test `tests/test_to_base.py::test_to_base[case3]` reproduces it.

algo 0.1.0, Python 3.12
