import pytest

from notes.models import Note


def test_title_is_required():
    with pytest.raises(ValueError):
        Note("   ")


def test_add_tag_normalizes_and_dedupes():
    note = Note("Groceries", tags=[])
    note.add_tag("  Weekly Shopping ")
    note.add_tag("weekly shopping")
    assert note.tags == ["weekly-shopping"]


def test_remove_tag():
    note = Note("Trip", tags=["travel", "todo"])
    note.remove_tag("TODO")
    assert note.tags == ["travel"]
