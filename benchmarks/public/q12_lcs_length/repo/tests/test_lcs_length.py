import pytest

from algo.lcs_length import lcs_length


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
        pytest.param(['fun', ''], 0, id='case2'),
        pytest.param(['witch', 'sandwich'], 2, id='case0'),
    ],
)
def test_lcs_length(args, expected):
    result = lcs_length(*args)
    assert _normalize(result) == _normalize(expected)
