"""Parse and format compact durations such as ``"1h30m"``."""
from __future__ import annotations

import re

_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_COMPONENT = re.compile(r"(\d+)([dhms])")
_FULL = re.compile(r"(?:\d+[dhms])+")


def parse_duration(text: str) -> int:
    """Parse a duration string into seconds.

    Components are an integer followed by a unit (``d``, ``h``, ``m``, ``s``),
    largest unit first, and may be separated by whitespace::

        parse_duration("1h30m")   -> 5400
        parse_duration("2d 4h")   -> 187200
    """
    compact = text.strip().lower()
    if not _FULL.fullmatch(compact):
        raise ValueError(f"invalid duration: {text!r}")
    seconds = 0
    last_size = None
    for amount, unit in _COMPONENT.findall(compact):
        size = _UNITS[unit]
        if last_size is not None and size >= last_size:
            raise ValueError(f"units out of order in duration: {text!r}")
        last_size = size
        seconds += int(amount) * size
    return seconds


def format_duration(seconds: int) -> str:
    """Inverse of :func:`parse_duration`, using the most compact form."""
    if seconds < 0:
        raise ValueError("duration must be non-negative")
    if seconds == 0:
        return "0s"
    parts = []
    for unit, size in _UNITS.items():
        amount, seconds = divmod(seconds, size)
        if amount:
            parts.append(f"{amount}{unit}")
    return "".join(parts)
