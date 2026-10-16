# `powerset` returns wrong results for some inputs

`powerset` in `algo/powerset.py` does not do what its docstring specifies for every input.

- `powerset(["a", "b", "c"])` returns `[['a', 'b', 'c']]`; expected `[[], ["c"], ["b"], ["b", "c"], ["a"], ["a", "c"], ["a", "b"], ["a", "b", "c"]]`.

The failing test `tests/test_powerset.py::test_powerset[case0]` reproduces it.

algo 0.1.0, Python 3.12
