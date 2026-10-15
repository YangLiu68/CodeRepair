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
        pytest.param([[2, 4, 6, 8, 10, 12, 14, 16, 18, 20], 18], 8, id='case3'),
        pytest.param([[3, 5, 6, 7, 8, 9, 12, 13, 14, 24, 26, 27], 0], -1, id='case4'),
        pytest.param([[3, 5, 6, 7, 8, 9, 12, 12, 14, 24, 26, 27], 12], 6, id='case5'),
        pytest.param([[24, 26, 28, 50, 59], 101], -1, id='case6'),
    ],
)
def test_hidden_find_in_sorted(args, expected):
    result = find_in_sorted(*args)
    assert _normalize(result) == _normalize(expected)
