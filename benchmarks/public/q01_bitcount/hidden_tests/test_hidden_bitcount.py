import pytest

from algo.bitcount import bitcount


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
        pytest.param([128], 1, id='case1'),
        pytest.param([3005], 9, id='case2'),
        pytest.param([13], 3, id='case3'),
        pytest.param([14], 3, id='case4'),
        pytest.param([27], 4, id='case5'),
        pytest.param([834], 4, id='case6'),
    ],
)
def test_hidden_bitcount(args, expected):
    result = bitcount(*args)
    assert _normalize(result) == _normalize(expected)
