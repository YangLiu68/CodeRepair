import pytest

from algo.sqrt import sqrt


@pytest.mark.parametrize(
    "args, expected",
    [
        pytest.param([2, 0.5], 1.5, id='case1'),
        pytest.param([2, 0.01], 1.4166666666666665, id='case0'),
    ],
)
def test_sqrt(args, expected):
    result = sqrt(*args)
    assert result == pytest.approx(expected, abs=args[-1])
