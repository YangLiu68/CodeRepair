import pytest

from filestore import FileStore, UnsafePathError, safe_join


def test_hidden_sibling_prefix_rejected():
    with pytest.raises(UnsafePathError):
        safe_join("/srv/data", "../data-backup/secrets.txt")


def test_hidden_store_cannot_read_sibling_dir(tmp_path):
    sibling = tmp_path / "data-old"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("secret")
    store = FileStore(str(tmp_path / "data"))
    with pytest.raises(UnsafePathError):
        store.read_text("../data-old/secret.txt")


def test_hidden_base_itself_is_allowed():
    assert safe_join("/srv/data", ".") == "/srv/data"
