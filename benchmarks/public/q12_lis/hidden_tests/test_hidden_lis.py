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
        pytest.param([[10, 20, 11, 32, 22, 48, 43]], 4, id='case2'),
        pytest.param([[4, 2, 1]], 1, id='case3'),
        pytest.param([[5, 1, 3, 4, 7]], 4, id='case4'),
        pytest.param([[4, 1]], 1, id='case5'),
        pytest.param([[10, 22, 9, 33, 21, 50, 41, 60, 80]], 6, id='case9'),
        pytest.param([[7, 10, 9, 2, 3, 8, 1]], 3, id='case10'),
        pytest.param([[9, 11, 2, 13, 7, 15]], 4, id='case11'),
    ],
)
def test_hidden_lis(args, expected):
    result = lis(*args)
    assert _normalize(result) == _normalize(expected)
