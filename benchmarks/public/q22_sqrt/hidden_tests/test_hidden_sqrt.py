import pytest

from algo.sqrt import sqrt


@pytest.mark.parametrize(
    "args, expected",
    [
        pytest.param([2, 0.3], 1.5, id='case2'),
        pytest.param([4, 0.2], 2, id='case3'),
        pytest.param([27, 0.01], 5.196164639727311, id='case4'),
        pytest.param([33, 0.05], 5.744627526262464, id='case5'),
        pytest.param([170, 0.03], 13.038404876679632, id='case6'),
    ],
)
def test_hidden_sqrt(args, expected):
    result = sqrt(*args)
    assert result == pytest.approx(expected, abs=args[-1])
