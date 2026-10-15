from notes.models import Note
from notes.store import NoteStore


def test_hidden_new_notes_do_not_share_tags():
    first = Note("first")
    first.add_tag("leaky")
    second = Note("second")
    assert second.tags == []


def test_hidden_store_notes_have_independent_tags():
    store = NoteStore()
    a = store.create("a")
    b = store.create("b")
    a.add_tag("x")
    assert b.tags == []
    assert store.by_tag("x") == [a]
