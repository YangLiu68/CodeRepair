"""Greedy word wrapping."""
from __future__ import annotations

from typing import List


def wrap(text: str, width: int) -> List[str]:
    """Wrap ``text`` into lines of at most ``width`` characters where possible."""
    if width < 1:
        raise ValueError("width must be positive")
    lines: List[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines
