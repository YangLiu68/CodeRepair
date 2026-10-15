"""Memoization on top of :class:`LRUCache`."""
from __future__ import annotations

import functools

from .lru import LRUCache


def memoize(capacity: int = 128):
    """Cache results of a function with hashable positional arguments."""

    def decorator(fn):
        cache: LRUCache = LRUCache(capacity)

        @functools.wraps(fn)
        def wrapper(*args):
            if args in cache:
                return cache.get(args)
            result = fn(*args)
            cache.put(args, result)
            return result

        wrapper.cache = cache
        return wrapper

    return decorator
