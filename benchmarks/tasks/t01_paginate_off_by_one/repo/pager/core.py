"""Simple list pagination helpers."""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Sequence, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Page:
    items: list
    number: int
    total_pages: int

    @property
    def has_next(self) -> bool:
        return self.number < self.total_pages

    @property
    def has_prev(self) -> bool:
        return self.number > 1


def total_pages(n_items: int, per_page: int) -> int:
    """Number of pages needed to show ``n_items`` (always at least one)."""
    if per_page <= 0:
        raise ValueError("per_page must be positive")
    return max(1, ceil(n_items / per_page))


def paginate(items: Sequence[T], page: int, per_page: int = 10) -> Page:
    """Return the 1-indexed ``page`` of ``items``."""
    pages = total_pages(len(items), per_page)
    if page < 1 or page > pages:
        raise ValueError(f"page {page} out of range 1..{pages}")
    start = page * per_page
    end = start + per_page
    return Page(list(items[start:end]), page, pages)
