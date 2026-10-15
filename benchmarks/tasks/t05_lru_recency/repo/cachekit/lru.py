"""A small least-recently-used cache."""
from __future__ import annotations

from collections import OrderedDict
from typing import Generic, Hashable, List, Optional, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")

_MISSING = object()


class LRUCache(Generic[K, V]):
    """Mapping with a fixed capacity that evicts the least recently used key.

    Both ``get`` (on a hit) and ``put`` count as a use. Membership tests do not.
    """

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = capacity
        self._data: OrderedDict = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        value = self._data.get(key, _MISSING)
        if value is _MISSING:
            self.misses += 1
            return default
        self.hits += 1
        return value

    def put(self, key: K, value: V) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        if len(self._data) > self.capacity:
            self._data.popitem(last=False)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def keys(self) -> List[K]:
        """Keys ordered from least to most recently used."""
        return list(self._data.keys())
