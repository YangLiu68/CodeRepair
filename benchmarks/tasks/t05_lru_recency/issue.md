# Cache evicts entries I just read

Repro:

```python
from cachekit import LRUCache

cache = LRUCache(2)
cache.put("a", 1)
cache.put("b", 2)
cache.get("a")       # "a" is now the most recently used key
cache.put("c", 3)    # should evict "b"
print("a" in cache)  # False ?!
```

Functions decorated with `@memoize` keep recomputing their hottest inputs because of
this. `tests/test_lru.py::test_get_refreshes_recency` reproduces it.
