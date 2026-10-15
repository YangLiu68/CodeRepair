"""Path helpers that keep user-supplied names inside a base directory."""
from __future__ import annotations

import os


class UnsafePathError(ValueError):
    """Raised when a user-supplied path would escape its base directory."""


def safe_join(base: str, *parts: str) -> str:
    """Join ``parts`` onto ``base`` and refuse any result outside ``base``.

    The check is lexical (no filesystem access): ``..`` segments are collapsed
    and absolute parts are rejected. ``base`` itself is a valid result.
    """
    base = os.path.normpath(os.path.abspath(base))
    for part in parts:
        if os.path.isabs(part):
            raise UnsafePathError(f"absolute path not allowed: {part!r}")
    candidate = os.path.normpath(os.path.join(base, *parts))
    if not candidate.startswith(base):
        raise UnsafePathError(f"path escapes base directory: {parts!r}")
    return candidate
