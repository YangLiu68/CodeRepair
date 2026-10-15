import pytest

from algo.find_in_sorted import find_in_sorted


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
        pytest.param([[3, 4, 5, 5, 5, 5, 6], 5], 3, id='case0'),
        pytest.param([[1, 2, 3, 4, 6, 7, 8], 4], 3, id='case2'),
        pytest.param([[1, 2, 3, 4, 6, 7, 8], 5], -1, id='case1'),
    ],
)
def test_find_in_sorted(args, expected):
    result = find_in_sorted(*args)
    assert _normalize(result) == _normalize(expected)
