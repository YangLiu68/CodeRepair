from __future__ import annotations

import pytest
from helpers import make_repo, snapshot_of

from coderepair.repo import ingest_repository
from coderepair.search import RepoIndex, is_test_path, module_name, tokenize


def test_tokenize_splits_identifiers_but_keeps_whole_names():
    tokens = tokenize("total_covered LRUCache parseDuration")
    for expected in (
        "total_covered",
        "total",
        "covered",
        "lrucache",
        "lru",
        "cache",
        "parse",
        "duration",
    ):
        assert expected in tokens
    assert "the" not in tokenize("the self return")


def test_module_name_and_test_detection():
    assert module_name("pkg/sub/mod.py") == "pkg.sub.mod"
    assert module_name("pkg/__init__.py") == "pkg"
    assert module_name("README.md") is None
    assert is_test_path("tests/test_x.py")
    assert is_test_path("pkg/foo_test.py")
    assert is_test_path("conftest.py")
    assert not is_test_path("pkg/testing_utils.py")
    assert not is_test_path("pkg/core.py")


def test_symbol_index():
    index = RepoIndex(snapshot_of("t05_lru_recency"))
    (get,) = index.find_symbol("LRUCache.get")
    assert (get.kind, get.path) == ("method", "cachekit/lru.py")
    assert get.line < get.end_line
    (memoize,) = index.find_symbol("memoize")
    assert memoize.kind == "function"
    assert {s.name for s in index.symbols_in("cachekit/lru.py")} >= {
        "LRUCache",
        "get",
        "put",
        "K",
        "V",
    }


def test_import_graph_resolves_relative_and_package_imports():
    index = RepoIndex(snapshot_of("t06_coupon_threshold_multifile"))
    assert index.imports["shop/cart.py"] == {"shop/coupons.py", "shop/pricing.py"}
    assert index.imports["tests/test_cart.py"] == {"shop/cart.py"}
    assert "shop/cart.py" in index.imported_by("shop/coupons.py")


def test_grep_literal_regex_and_glob():
    index = RepoIndex(snapshot_of("t05_lru_recency"))
    literal = index.grep("move_to_end")
    assert [(m.path, m.line) for m in literal] == [("cachekit/lru.py", 37)]
    regex = index.grep(r"def (get|put)\b", regex=True)
    assert {m.text.strip()[:7] for m in regex} == {"def get", "def put"}
    assert all(m.path.startswith("tests/") for m in index.grep("LRUCache", path_glob="tests/*"))
    assert index.grep("") == []


def test_grep_rejects_oversized_regex():
    index = RepoIndex(snapshot_of("t05_lru_recency"))
    with pytest.raises(ValueError):
        index.grep("a" * 500, regex=True)


def test_read_numbers_lines():
    index = RepoIndex(snapshot_of("t01_paginate_off_by_one"))
    excerpt = index.read("pager/core.py", 37, 38)
    assert excerpt.splitlines()[0].startswith("   37  ")
    assert "start = page * per_page" in excerpt


def test_unparseable_python_is_recorded_not_fatal(tmp_path):
    repo = make_repo(tmp_path / "r", {"ok.py": "def f():\n    return 1\n", "bad.py": "def (:\n"})
    index = RepoIndex(ingest_repository(repo, (tmp_path,)))
    assert "bad.py" in index.parse_errors
    assert index.find_symbol("f")


def test_bm25_prefers_relevant_file():
    index = RepoIndex(snapshot_of("t09_slugify_accents"))
    scores = index.bm25(tokenize("slugify accented letters transliterated"))
    assert max(scores, key=scores.get) == "textkit/slug.py"
