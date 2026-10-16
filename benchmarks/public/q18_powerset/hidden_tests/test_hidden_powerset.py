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
        pytest.param([['a', 'b']], [[], ['b'], ['a'], ['a', 'b']], id='case1'),
        pytest.param([['a']], [[], ['a']], id='case2'),
        pytest.param([['x', 'df', 'z', 'm']], [[], ['m'], ['z'], ['z', 'm'], ['df'], ['df', 'm'], ['df', 'z'], ['df', 'z', 'm'], ['x'], ['x', 'm'], ['x', 'z'], ['x', 'z', 'm'], ['x', 'df'], ['x', 'df', 'm'], ['x', 'df', 'z'], ['x', 'df', 'z', 'm']], id='case4'),
    ],
)
def test_hidden_powerset(args, expected):
    result = powerset(*args)
    assert _subsets(result) == _subsets(expected)
