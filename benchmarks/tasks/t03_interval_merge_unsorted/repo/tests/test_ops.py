import pytest

from intervals import merge, total_covered


def test_merge_overlapping_sorted_input():
    assert merge([(1, 3), (2, 6), (8, 10)]) == [(1, 6), (8, 10)]


def test_merge_shared_endpoint():
    assert merge([(1, 3), (3, 5)]) == [(1, 5)]


def test_validate_rejects_reversed():
    with pytest.raises(ValueError):
        merge([(5, 1)])


def test_total_covered_sorted_input():
    assert total_covered([(0, 2), (4, 5)]) == 3


def test_total_covered_unsorted_input():
    assert total_covered([(5, 8), (1, 6)]) == 7
