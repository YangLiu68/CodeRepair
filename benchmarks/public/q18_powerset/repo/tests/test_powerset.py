import pytest

from algo.powerset import powerset


def _normalize(value):
    """Compare results structurally: tuples as lists, iterators materialised."""
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if hasattr(value, "__next__"):
        return [_normalize(v) for v in value]
    return value


def _subsets(value):
    return sorted(sorted(repr(v) for v in subset) for subset in value)


@pytest.mark.parametrize(
    "args, expected",
    [
        pytest.param([[]], [[]], id='case3'),
        pytest.param([['a', 'b', 'c']], [[], ['c'], ['b'], ['b', 'c'], ['a'], ['a', 'c'], ['a', 'b'], ['a', 'b', 'c']], id='case0'),
    ],
)
def test_powerset(args, expected):
    result = powerset(*args)
    assert _subsets(result) == _subsets(expected)
