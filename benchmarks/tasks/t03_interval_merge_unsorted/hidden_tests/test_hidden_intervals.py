from intervals import contains, merge


def test_hidden_merge_returns_sorted_union():
    assert merge([(10, 12), (1, 2), (2, 4)]) == [(1, 4), (10, 12)]


def test_hidden_contains_after_unsorted_merge():
    assert contains([(7, 9), (0, 7)], 3) is True
