import pytest

from pager import paginate, total_pages


def test_total_pages_rounds_up():
    assert total_pages(25, 10) == 3


def test_total_pages_empty_is_one():
    assert total_pages(0, 10) == 1


def test_total_pages_rejects_non_positive():
    with pytest.raises(ValueError):
        total_pages(10, 0)


def test_out_of_range_page_rejected():
    with pytest.raises(ValueError):
        paginate(list(range(25)), 4)


def test_first_page_starts_at_first_item():
    page = paginate(list(range(25)), 1)
    assert page.items == list(range(10))
    assert page.has_prev is False
