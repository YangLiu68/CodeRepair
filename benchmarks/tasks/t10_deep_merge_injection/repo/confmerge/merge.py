"""Deep-merge configuration dictionaries."""
from __future__ import annotations

import copy
from typing import Any, Dict


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Return a new dict with ``override`` merged into ``base``.

    Nested dictionaries are merged recursively at every depth; any other value
    in ``override`` replaces the value in ``base``. Neither input is modified.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = {**result[key], **value}
        else:
            result[key] = copy.deepcopy(value)
    return result
