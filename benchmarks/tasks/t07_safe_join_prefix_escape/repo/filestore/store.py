"""A tiny file store rooted at one directory."""
from __future__ import annotations

from pathlib import Path

from .paths import safe_join


class FileStore:
    def __init__(self, root: str) -> None:
        self.root = str(Path(root).resolve())

    def path_for(self, name: str) -> str:
        return safe_join(self.root, name)

    def write_text(self, name: str, content: str) -> None:
        path = Path(self.path_for(name))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def read_text(self, name: str) -> str:
        return Path(self.path_for(name)).read_text(encoding="utf-8")
