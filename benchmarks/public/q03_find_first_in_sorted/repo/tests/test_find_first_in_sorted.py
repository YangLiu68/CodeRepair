import pytest

from algo.find_first_in_sorted import find_first_in_sorted


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
        pytest.param([[3, 4, 5, 5, 5, 5, 6], 5], 2, id='case0'),
        pytest.param([[3, 6, 7, 9, 9, 10, 14, 27], 14], 6, id='case3'),
    ],
)
def test_find_first_in_sorted(args, expected):
    result = find_first_in_sorted(*args)
    assert _normalize(result) == _normalize(expected)
