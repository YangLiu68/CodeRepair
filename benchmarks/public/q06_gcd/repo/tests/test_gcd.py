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
        pytest.param([17, 0], 17, id='case0'),
        pytest.param([13, 13], 13, id='case1'),
    ],
)
def test_gcd(args, expected):
    result = gcd(*args)
    assert _normalize(result) == _normalize(expected)
