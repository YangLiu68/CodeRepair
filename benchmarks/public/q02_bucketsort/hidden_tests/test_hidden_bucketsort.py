import pytest

from algo.bucketsort import bucketsort


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
        pytest.param([[3, 2, 4, 2, 3, 5], 6], [2, 2, 3, 3, 4, 5], id='case2'),
        pytest.param([[1, 3, 4, 6, 4, 2, 9, 1, 2, 9], 10], [1, 1, 2, 2, 3, 4, 4, 6, 9, 9], id='case3'),
        pytest.param([[20, 19, 18, 17, 16, 15, 14, 13, 12, 11], 21], [11, 12, 13, 14, 15, 16, 17, 18, 19, 20], id='case4'),
        pytest.param([[20, 21, 22, 23, 24, 25, 26, 27, 28, 29], 30], [20, 21, 22, 23, 24, 25, 26, 27, 28, 29], id='case5'),
        pytest.param([[8, 5, 3, 1, 9, 6, 0, 7, 4, 2, 5], 10], [0, 1, 2, 3, 4, 5, 5, 6, 7, 8, 9], id='case6'),
    ],
)
def test_hidden_bucketsort(args, expected):
    result = bucketsort(*args)
    assert _normalize(result) == _normalize(expected)
