import pytest

from algo.to_base import to_base


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
        pytest.param([8227, 18], '1771', id='case0'),
        pytest.param([73, 8], '111', id='case1'),
        pytest.param([31, 16], '1F', id='case3'),
    ],
)
def test_to_base(args, expected):
    result = to_base(*args)
    assert _normalize(result) == _normalize(expected)
