import pytest

from algo.mergesort import mergesort


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
        pytest.param([[1, 2, 6, 72, 7, 33, 4]], [1, 2, 4, 6, 7, 33, 72], id='case1'),
    ],
)
def test_mergesort(args, expected):
    result = mergesort(*args)
    assert _normalize(result) == _normalize(expected)
