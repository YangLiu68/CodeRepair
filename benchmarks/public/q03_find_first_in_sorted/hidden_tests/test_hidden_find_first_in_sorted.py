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
        pytest.param([[3, 4, 5, 5, 5, 5, 6], 7], -1, id='case1'),
        pytest.param([[3, 4, 5, 5, 5, 5, 6], 2], -1, id='case2'),
        pytest.param([[0, 1, 6, 8, 13, 14, 67, 128], 80], -1, id='case4'),
        pytest.param([[0, 1, 6, 8, 13, 14, 67, 128], 67], 6, id='case5'),
        pytest.param([[0, 1, 6, 8, 13, 14, 67, 128], 128], 7, id='case6'),
    ],
)
def test_hidden_find_first_in_sorted(args, expected):
    result = find_first_in_sorted(*args)
    assert _normalize(result) == _normalize(expected)
