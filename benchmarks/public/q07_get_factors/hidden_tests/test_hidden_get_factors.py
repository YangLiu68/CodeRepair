import pytest

from algo.get_factors import get_factors


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
        pytest.param([101], [101], id='case2'),
        pytest.param([104], [2, 2, 2, 13], id='case3'),
        pytest.param([2], [2], id='case4'),
        pytest.param([3], [3], id='case5'),
        pytest.param([17], [17], id='case6'),
        pytest.param([63], [3, 3, 7], id='case7'),
    ],
)
def test_hidden_get_factors(args, expected):
    result = get_factors(*args)
    assert _normalize(result) == _normalize(expected)
