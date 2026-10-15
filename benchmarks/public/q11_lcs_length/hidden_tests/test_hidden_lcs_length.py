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
        pytest.param(['meow', 'homeowner'], 4, id='case1'),
        pytest.param(['fun', 'function'], 3, id='case3'),
        pytest.param(['cyborg', 'cyber'], 3, id='case4'),
        pytest.param(['physics', 'physics'], 7, id='case5'),
        pytest.param(['space age', 'pace a'], 6, id='case6'),
        pytest.param(['flippy', 'floppy'], 3, id='case7'),
    ],
)
def test_hidden_lcs_length(args, expected):
    result = lcs_length(*args)
    assert _normalize(result) == _normalize(expected)
