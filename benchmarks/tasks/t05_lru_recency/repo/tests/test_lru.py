import pytest

from cachekit import LRUCache


def test_capacity_must_be_positive():
    with pytest.raises(ValueError):
        LRUCache(0)


def test_put_and_get():
    cache = LRUCache(2)
    cache.put("a", 1)
    assert cache.get("a") == 1
    assert cache.get("missing", 0) == 0


def test_hit_and_miss_counters():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.get("a")
    cache.get("b")
    assert (cache.hits, cache.misses) == (1, 1)


def test_capacity_evicts_oldest_insert():
    cache = LRUCache(2)
    for key in "abc":
        cache.put(key, key)
    assert "a" not in cache
    assert len(cache) == 2


def test_contains_does_not_refresh_recency():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert "a" in cache
    cache.put("c", 3)
    assert "a" not in cache


def test_get_refreshes_recency():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)
    assert "a" in cache
    assert "b" not in cache
