from cachekit import LRUCache, memoize


def test_hidden_keys_order_tracks_reads():
    cache = LRUCache(3)
    for key in "abc":
        cache.put(key, key)
    cache.get("a")
    assert cache.keys() == ["b", "c", "a"]


def test_hidden_memoize_keeps_hot_entry():
    calls = []

    @memoize(capacity=2)
    def square(x):
        calls.append(x)
        return x * x

    for x in (1, 2, 1, 3, 1):
        square(x)
    assert calls == [1, 2, 3]
