import pytest

from algo.lis import lis


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
        pytest.param([[]], 0, id='case0'),
        pytest.param([[3]], 1, id='case1'),
        pytest.param([[4, 1, 5, 3, 7, 6, 2]], 3, id='case8'),
    ],
)
def test_lis(args, expected):
    result = lis(*args)
    assert _normalize(result) == _normalize(expected)
