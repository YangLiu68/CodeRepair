"""Human-friendly descriptions of durations."""
from __future__ import annotations

from .duration import parse_duration

_NAMES = [(86400, "day"), (3600, "hour"), (60, "minute"), (1, "second")]


def humanize(seconds: int) -> str:
    if seconds == 0:
        return "0 seconds"
    words = []
    for size, name in _NAMES:
        amount, seconds = divmod(seconds, size)
        if amount:
            words.append(f"{amount} {name}{'' if amount == 1 else 's'}")
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " and " + words[-1]


def humanize_text(text: str) -> str:
    return humanize(parse_duration(text))
