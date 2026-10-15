import pytest

from algo.kheapsort import kheapsort


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
        pytest.param([[1, 2, 3, 4, 5], 0], [1, 2, 3, 4, 5], id='case0'),
        pytest.param([[3, 2, 1, 5, 4], 2], [1, 2, 3, 4, 5], id='case1'),
    ],
)
def test_kheapsort(args, expected):
    result = kheapsort(*args)
    assert _normalize(result) == _normalize(expected)
