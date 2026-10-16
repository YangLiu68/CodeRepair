import pytest

from algo.sieve import sieve


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
        pytest.param([4], [2, 3], id='case2'),
        pytest.param([7], [2, 3, 5, 7], id='case3'),
        pytest.param([20], [2, 3, 5, 7, 11, 13, 17, 19], id='case4'),
        pytest.param([50], [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47], id='case5'),
    ],
)
def test_hidden_sieve(args, expected):
    result = sieve(*args)
    assert _normalize(result) == _normalize(expected)
