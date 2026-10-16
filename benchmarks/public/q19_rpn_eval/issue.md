# `rpn_eval` returns wrong results for some inputs

`rpn_eval` in `algo/rpn_eval.py` does not do what its docstring specifies for every input.

- `rpn_eval([3.0, 5.0, "+", 2.0, "/"])` returns `0.25`; expected `4.0`.

algo 0.1.0, Python 3.12
