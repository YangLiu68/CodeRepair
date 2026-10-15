import pytest

from algo.gcd import gcd


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
        pytest.param([37, 600], 1, id='case2'),
        pytest.param([20, 100], 20, id='case3'),
        pytest.param([624129, 2061517], 18913, id='case4'),
        pytest.param([3, 12], 3, id='case5'),
    ],
)
def test_hidden_gcd(args, expected):
    result = gcd(*args)
    assert _normalize(result) == _normalize(expected)
