from __future__ import annotations

import os

import pytest
from helpers import TASKS_DIR, make_repo, snapshot_of, task

from coderepair.config import Limits
from coderepair.repo import ingest_repository, read_git_head
from coderepair.security import PolicyError

SHA = "0123456789abcdef0123456789abcdef01234567"


def test_fixture_snapshot_contains_only_the_visible_repo():
    snapshot = snapshot_of("t01_paginate_off_by_one")
    assert snapshot.paths() == [
        "pager/__init__.py",
        "pager/core.py",
        "pyproject.toml",
        "tests/test_core.py",
    ]
    assert snapshot.root == task("t01_paginate_off_by_one").repo_dir.resolve()


def test_snapshot_hash_is_deterministic_and_content_sensitive(tmp_path):
    repo = make_repo(tmp_path / "repo", {"a.py": "x = 1\n", "pkg/b.py": "y = 2\n"})
    first = ingest_repository(repo, (tmp_path,))
    second = ingest_repository(repo, (tmp_path,))
    assert first.content_hash == second.content_hash
    (repo / "a.py").write_text("x = 2\n")
    assert ingest_repository(repo, (tmp_path,)).content_hash != first.content_hash


def test_ingestion_excludes_unsafe_and_irrelevant_files(tmp_path):
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("TOP SECRET")
    repo = make_repo(
        tmp_path / "repo",
        {
            "app.py": "print('hi')\n",
            ".env": "API_KEY=supersecretvalue\n",
            ".env.example": "API_KEY=\n",
            "deploy/id_rsa": "-----BEGIN OPENSSH PRIVATE KEY-----\n",
            "logo.png": b"\x89PNG\r\n\x1a\n\x00\x00binary",
            "big.txt": "x" * 2_000,
            "latin1.txt": "caf\xe9".encode("latin-1"),
            "__pycache__/app.cpython-312.pyc": b"\x00\x01",
            "node_modules/lib/index.js": "module.exports = 1\n",
            ".git/HEAD": "ref: refs/heads/main\n",
            ".git/refs/heads/main": SHA + "\n",
        },
    )
    os.symlink(outside, repo / "link_to_outside.txt")
    os.symlink(tmp_path, repo / "linked_dir", target_is_directory=True)

    snapshot = ingest_repository(repo, (tmp_path,), Limits(max_file_bytes=1_000))

    assert snapshot.paths() == [".env.example", "app.py"]
    reasons = {e.path: e.reason for e in snapshot.excluded}
    assert reasons[".env"] == "sensitive"
    assert reasons["deploy/id_rsa"] == "sensitive"
    assert reasons["logo.png"] == "binary"
    assert reasons["big.txt"] == "too-large"
    assert reasons["latin1.txt"] == "not-utf8"
    assert reasons["link_to_outside.txt"] == "symlink"
    assert reasons["linked_dir/"] == "symlink"
    assert reasons["__pycache__/"] == "ignored-directory"
    assert reasons["node_modules/"] == "ignored-directory"
    assert reasons[".git/"] == "ignored-directory"
    assert snapshot.git_head == SHA
    all_text = "".join(f.text for f in snapshot.files.values())
    assert "supersecretvalue" not in all_text
    assert "TOP SECRET" not in all_text


def test_ingestion_enforces_file_count_and_total_size_limits(tmp_path):
    repo = make_repo(tmp_path / "repo", {f"m{i}.py": "x = 1\n" * 10 for i in range(5)})
    by_count = ingest_repository(repo, (tmp_path,), Limits(max_files=3))
    assert len(by_count.files) == 3
    assert sum(e.reason == "file-count-limit" for e in by_count.excluded) == 2
    by_size = ingest_repository(repo, (tmp_path,), Limits(max_total_bytes=130))
    assert len(by_size.files) == 2
    assert sum(e.reason == "total-size-limit" for e in by_size.excluded) == 3


def test_ingestion_applies_the_path_policy(tmp_path):
    with pytest.raises(PolicyError):
        ingest_repository(TASKS_DIR / "t01_paginate_off_by_one" / "repo", (tmp_path,))


def test_git_head_from_packed_refs(tmp_path):
    make_repo(
        tmp_path,
        {
            ".git/HEAD": "ref: refs/heads/dev\n",
            ".git/packed-refs": f"# pack\n{SHA} refs/heads/dev\n",
        },
    )
    assert read_git_head(tmp_path) == SHA


@pytest.mark.parametrize(
    "head",
    ["ref: ../../../../etc/passwd\n", "ref: refs/heads/../../../../etc/passwd\n", "garbage\n"],
)
def test_git_head_rejects_malicious_refs(tmp_path, head):
    make_repo(tmp_path, {".git/HEAD": head})
    assert read_git_head(tmp_path) is None


def test_git_head_detached(tmp_path):
    make_repo(tmp_path, {".git/HEAD": SHA + "\n"})
    assert read_git_head(tmp_path) == SHA
