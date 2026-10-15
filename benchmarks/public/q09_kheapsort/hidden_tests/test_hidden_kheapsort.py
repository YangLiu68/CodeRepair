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
        pytest.param([[5, 4, 3, 2, 1], 4], [1, 2, 3, 4, 5], id='case2'),
        pytest.param([[3, 12, 5, 1, 6], 3], [1, 3, 5, 6, 12], id='case3'),
    ],
)
def test_hidden_kheapsort(args, expected):
    result = kheapsort(*args)
    assert _normalize(result) == _normalize(expected)
