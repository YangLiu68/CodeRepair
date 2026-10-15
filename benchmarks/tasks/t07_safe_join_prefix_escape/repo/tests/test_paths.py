import pytest

from filestore.paths import UnsafePathError, safe_join


def test_join_simple():
    assert safe_join("/srv/data", "a", "b.txt") == "/srv/data/a/b.txt"


def test_dotdot_inside_base_is_allowed():
    assert safe_join("/srv/data", "a/../b.txt") == "/srv/data/b.txt"


def test_parent_escape_rejected():
    with pytest.raises(UnsafePathError):
        safe_join("/srv/data", "../etc/passwd")


def test_absolute_part_rejected():
    with pytest.raises(UnsafePathError):
        safe_join("/srv/data", "/etc/passwd")
