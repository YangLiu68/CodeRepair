"""Operations on closed integer intervals represented as ``(start, end)`` tuples."""
from __future__ import annotations

from typing import List, Tuple

Interval = Tuple[int, int]


def validate(interval: Interval) -> Interval:
    start, end = interval
    if start > end:
        raise ValueError(f"invalid interval {interval!r}: start > end")
    return start, end


def merge(intervals: List[Interval]) -> List[Interval]:
    """Merge overlapping intervals (intervals that share an endpoint overlap).

    The result is sorted by start and contains no overlapping intervals.
    """
    merged: List[Interval] = []
    for start, end in map(validate, intervals):
        if merged and start <= merged[-1][1]:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def total_covered(intervals: List[Interval]) -> int:
    """Total length covered by the union of ``intervals``."""
    return sum(end - start for start, end in merge(intervals))


def contains(intervals: List[Interval], point: int) -> bool:
    return any(start <= point <= end for start, end in merge(intervals))
