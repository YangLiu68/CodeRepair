"""Note model."""
from __future__ import annotations

from datetime import datetime, timezone


def normalize_tag(tag: str) -> str:
    return tag.strip().lower().replace(" ", "-")


class Note:
    def __init__(self, title: str, body: str = "", tags: list[str] = []) -> None:
        if not title.strip():
            raise ValueError("title must not be empty")
        self.title = title.strip()
        self.body = body
        self.tags = tags
        self.created_at = datetime.now(timezone.utc)

    def add_tag(self, tag: str) -> None:
        tag = normalize_tag(tag)
        if tag and tag not in self.tags:
            self.tags.append(tag)

    def remove_tag(self, tag: str) -> None:
        tag = normalize_tag(tag)
        if tag in self.tags:
            self.tags.remove(tag)

    def __repr__(self) -> str:
        return f"Note({self.title!r}, tags={self.tags!r})"
