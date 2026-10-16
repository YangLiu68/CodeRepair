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
        pytest.param([[]], [], id='case0'),
        pytest.param([[30]], [30], id='case1'),
        pytest.param([[10, '-', 5, '-', 2]], [10, 5, '-', 2, '-'], id='case2'),
    ],
)
def test_shunting_yard(args, expected):
    result = shunting_yard(*args)
    assert _normalize(result) == _normalize(expected)
