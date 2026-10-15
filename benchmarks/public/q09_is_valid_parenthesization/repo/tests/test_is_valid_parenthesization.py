import pytest

from algo.is_valid_parenthesization import is_valid_parenthesization


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
        pytest.param(['((()()))()'], True, id='case0'),
        pytest.param([')()('], False, id='case1'),
    ],
)
def test_is_valid_parenthesization(args, expected):
    result = is_valid_parenthesization(*args)
    assert _normalize(result) == _normalize(expected)
