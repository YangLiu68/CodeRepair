import pytest

from algo.kth import kth


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
        pytest.param([[3, 6, 7, 1, 6, 3, 8, 9], 2], 3, id='case2'),
        pytest.param([[2, 6, 8, 3, 5, 7], 0], 2, id='case3'),
        pytest.param([[1, 2, 3, 4, 5, 6, 7], 4], 5, id='case0'),
    ],
)
def test_kth(args, expected):
    result = kth(*args)
    assert _normalize(result) == _normalize(expected)
