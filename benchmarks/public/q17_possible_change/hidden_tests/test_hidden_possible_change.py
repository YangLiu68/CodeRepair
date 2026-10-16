import pytest

from algo.possible_change import possible_change


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
        pytest.param([[1, 5, 10, 25], 75], 121, id='case2'),
        pytest.param([[1, 5, 10, 25], 34], 18, id='case3'),
        pytest.param([[1, 5, 10], 34], 16, id='case4'),
        pytest.param([[1, 5, 10, 25], 140], 568, id='case5'),
        pytest.param([[1, 5, 10, 25, 50], 140], 786, id='case6'),
        pytest.param([[1, 5, 10, 25, 50, 100], 140], 817, id='case7'),
    ],
)
def test_hidden_possible_change(args, expected):
    result = possible_change(*args)
    assert _normalize(result) == _normalize(expected)
