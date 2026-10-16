import pytest

from algo.next_permutation import next_permutation


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
        pytest.param([[3, 5, 6, 2, 1]], [3, 6, 1, 2, 5], id='case1'),
        pytest.param([[3, 5, 6, 2]], [3, 6, 2, 5], id='case2'),
        pytest.param([[4, 5, 1, 7, 9]], [4, 5, 1, 9, 7], id='case3'),
        pytest.param([[4, 5, 8, 7, 1]], [4, 7, 1, 5, 8], id='case4'),
        pytest.param([[9, 5, 2, 6, 1]], [9, 5, 6, 1, 2], id='case5'),
        pytest.param([[44, 5, 1, 7, 9]], [44, 5, 1, 9, 7], id='case6'),
    ],
)
def test_hidden_next_permutation(args, expected):
    result = next_permutation(*args)
    assert _normalize(result) == _normalize(expected)
