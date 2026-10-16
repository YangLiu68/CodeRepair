import pytest

from algo.max_sublist_sum import max_sublist_sum


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
        pytest.param([[0, -1, 2, -1, 3, -1, 0]], 4, id='case1'),
        pytest.param([[4, -2, -8, 5, -2, 7, 7, 2, -6, 5]], 19, id='case3'),
        pytest.param([[-2, 1, -3, 4, -1, 2, 1, -5, 4]], 6, id='case5'),
    ],
)
def test_hidden_max_sublist_sum(args, expected):
    result = max_sublist_sum(*args)
    assert _normalize(result) == _normalize(expected)
