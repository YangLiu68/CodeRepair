from pager import paginate


def test_hidden_last_page_is_partial():
    page = paginate(list(range(25)), 3)
    assert page.items == [20, 21, 22, 23, 24]
    assert page.has_next is False


def test_hidden_per_page_one_walks_every_item():
    items = ["a", "b", "c"]
    assert [paginate(items, n, per_page=1).items for n in (1, 2, 3)] == [["a"], ["b"], ["c"]]
