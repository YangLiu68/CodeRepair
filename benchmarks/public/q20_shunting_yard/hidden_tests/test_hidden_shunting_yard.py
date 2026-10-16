import pytest

from algo.shunting_yard import shunting_yard


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
        pytest.param([[34, '-', 12, '/', 5]], [34, 12, 5, '/', '-'], id='case3'),
        pytest.param([[4, '+', 9, '*', 9, '-', 10, '+', 13]], [4, 9, 9, '*', '+', 10, '-', 13, '+'], id='case4'),
        pytest.param([[7, '*', 43, '-', 7, '+', 13, '/', 7]], [7, 43, '*', 7, '-', 13, 7, '/', '+'], id='case5'),
    ],
)
def test_hidden_shunting_yard(args, expected):
    result = shunting_yard(*args)
    assert _normalize(result) == _normalize(expected)
