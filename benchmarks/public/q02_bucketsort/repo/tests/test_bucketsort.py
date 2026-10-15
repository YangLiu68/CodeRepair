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
        pytest.param([[], 14], [], id='case0'),
        pytest.param([[3, 11, 2, 9, 1, 5], 12], [1, 2, 3, 5, 9, 11], id='case1'),
    ],
)
def test_bucketsort(args, expected):
    result = bucketsort(*args)
    assert _normalize(result) == _normalize(expected)
