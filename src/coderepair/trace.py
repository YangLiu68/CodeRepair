"""Append-only run traces, written as JSON Lines."""

from __future__ import annotations

import json
import re
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[a-z0-9_]{1,40}-[0-9a-f]{6}$")


def new_run_id(label: str) -> str:
    safe = re.sub(r"[^a-z0-9_]+", "_", label.lower()).strip("_")[:40] or "run"
    return f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{safe}-{secrets.token_hex(3)}"


class Trace:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.events: list[dict[str, Any]] = []
        self._t0 = time.monotonic()

    def add(self, kind: str, **data: Any) -> dict[str, Any]:
        event = {
            "seq": len(self.events),
            "t": round(time.monotonic() - self._t0, 4),
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "kind": kind,
            **data,
        }
        self.events.append(event)
        return event

    def write_jsonl(self, path: Path) -> None:
        with path.open("w", encoding="utf-8") as fh:
            for event in self.events:
                fh.write(json.dumps(event, default=str, ensure_ascii=False) + "\n")


def read_trace(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
