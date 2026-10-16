import pytest

from algo.subsequences import subsequences


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
        pytest.param([30, -2, 3], [], id='case1'),
        pytest.param([30, 2, 3], [], id='case2'),
    ],
)
def test_subsequences(args, expected):
    result = subsequences(*args)
    assert sorted(_normalize(result)) == sorted(_normalize(expected))
