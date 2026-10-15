"""In-memory note store."""
from __future__ import annotations

from .models import Note, normalize_tag


class NoteStore:
    def __init__(self) -> None:
        self._notes: dict[str, Note] = {}

    def create(self, title: str, body: str = "") -> Note:
        if title in self._notes:
            raise KeyError(f"note {title!r} already exists")
        note = Note(title, body)
        self._notes[title] = note
        return note

    def get(self, title: str) -> Note:
        return self._notes[title]

    def by_tag(self, tag: str) -> list[Note]:
        tag = normalize_tag(tag)
        return [note for note in self._notes.values() if tag in note.tags]

    def __len__(self) -> int:
        return len(self._notes)
