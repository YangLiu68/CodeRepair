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
        pytest.param([16, 19], 'G', id='case2'),
        pytest.param([41, 2], '101001', id='case4'),
        pytest.param([44, 5], '134', id='case5'),
        pytest.param([27, 23], '14', id='case6'),
        pytest.param([56, 23], '2A', id='case7'),
        pytest.param([8237, 24], 'E75', id='case8'),
        pytest.param([8237, 34], '749', id='case9'),
    ],
)
def test_hidden_to_base(args, expected):
    result = to_base(*args)
    assert _normalize(result) == _normalize(expected)
