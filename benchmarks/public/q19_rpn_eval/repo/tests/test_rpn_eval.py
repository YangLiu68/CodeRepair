import pytest

from algo.rpn_eval import rpn_eval


def _normalize(value):
    """Compare results structurally: tuples as lists, iterators materialised."""
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if hasattr(value, "__next__"):
        return [_normalize(v) for v in value]
    return value


@pytest.mark.parametrize(
    "args, expected",
    [
        pytest.param([[2.0, 2.0, '+']], 4.0, id='case1'),
        pytest.param([[1.0, 2.0, '*', 3.0, 4.0, '*', '+']], 14.0, id='case3'),
    ],
)
def test_rpn_eval(args, expected):
    result = rpn_eval(*args)
    assert _normalize(result) == _normalize(expected)
