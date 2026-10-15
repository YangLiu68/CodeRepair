import pytest

from notes.store import NoteStore


def test_create_and_get():
    store = NoteStore()
    note = store.create("Ideas", "a note")
    assert store.get("Ideas") is note
    assert len(store) == 1


def test_duplicate_title_rejected():
    store = NoteStore()
    store.create("Ideas")
    with pytest.raises(KeyError):
        store.create("Ideas")


def test_by_tag_is_case_insensitive():
    store = NoteStore()
    note = store.create("Plan")
    note.add_tag("Urgent")
    assert store.by_tag("URGENT") == [note]
