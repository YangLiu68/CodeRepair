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
        pytest.param([[3, 4, 5]], 12, id='case2'),
        pytest.param([[-4, -4, -5]], 0, id='case4'),
    ],
)
def test_max_sublist_sum(args, expected):
    result = max_sublist_sum(*args)
    assert _normalize(result) == _normalize(expected)
