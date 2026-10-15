import pytest

from filestore import FileStore, UnsafePathError


def test_roundtrip(tmp_path):
    store = FileStore(str(tmp_path / "data"))
    store.write_text("notes/today.txt", "hello")
    assert store.read_text("notes/today.txt") == "hello"


def test_escape_rejected(tmp_path):
    store = FileStore(str(tmp_path / "data"))
    with pytest.raises(UnsafePathError):
        store.read_text("../../etc/passwd")
