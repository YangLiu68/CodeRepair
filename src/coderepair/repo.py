"""Read-only repository ingestion.

A repository is loaded once into an immutable in-memory :class:`RepoSnapshot`.
All later steps (search, retrieval, prompting, patch validation) work on the
snapshot, never on the live directory, and nothing here writes to disk or runs
programs. In particular ``git`` is never executed on an untrusted repository:
repository config can make git run arbitrary commands (``core.fsmonitor``,
filters, hooks), so the commit id is read directly from ``.git/HEAD`` instead.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from .config import Limits
from .security import IGNORED_DIR_NAMES, is_sensitive_path, resolve_repo_root

_BINARY_SNIFF_BYTES = 8192
_REF_RE = re.compile(r"^refs/[A-Za-z0-9._/\-]+$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


@dataclass(frozen=True)
class RepoFile:
    path: str
    text: str
    sha256: str

    @property
    def size(self) -> int:
        return len(self.text.encode("utf-8"))

    @property
    def line_count(self) -> int:
        return self.text.count("\n") + (0 if self.text.endswith("\n") or not self.text else 1)


@dataclass(frozen=True)
class Exclusion:
    path: str
    reason: str


@dataclass(frozen=True)
class RepoSnapshot:
    root: Path
    files: Mapping[str, RepoFile]
    excluded: tuple[Exclusion, ...]
    content_hash: str
    git_head: str | None

    def paths(self) -> list[str]:
        return sorted(self.files)

    def get(self, path: str) -> RepoFile | None:
        return self.files.get(path)

    def text(self, path: str) -> str:
        file = self.files.get(path)
        if file is None:
            raise KeyError(f"{path!r} is not in the repository snapshot")
        return file.text


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular_file(path: Path, max_bytes: int) -> bytes | str:
    """Read a regular file without following a symlink at the final component.

    Returns the bytes, or an exclusion reason string.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return "unreadable-or-symlink"
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return "not-a-regular-file"
        if info.st_size > max_bytes:
            return "too-large"
        chunks = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > max_bytes:
            return "too-large"
        return data
    finally:
        os.close(fd)


def read_git_head(root: Path) -> str | None:
    """Return the commit id checked out in ``root`` by parsing ``.git`` files (no git process)."""
    git_dir = root / ".git"
    if git_dir.is_symlink() or not git_dir.is_dir():
        return None
    head = _read_regular_file(git_dir / "HEAD", 4096)
    if not isinstance(head, bytes):
        return None
    value = head.decode("ascii", "replace").strip()
    if _SHA_RE.match(value):
        return value
    if not value.startswith("ref: "):
        return None
    ref = value[5:].strip()
    if not _REF_RE.match(ref) or ".." in ref.split("/"):
        return None
    loose = _read_regular_file(git_dir / ref, 4096)
    if isinstance(loose, bytes):
        sha = loose.decode("ascii", "replace").strip()
        return sha if _SHA_RE.match(sha) else None
    packed = _read_regular_file(git_dir / "packed-refs", 1_000_000)
    if isinstance(packed, bytes):
        for line in packed.decode("utf-8", "replace").splitlines():
            parts = line.split(" ", 1)
            if len(parts) == 2 and parts[1].strip() == ref and _SHA_RE.match(parts[0]):
                return parts[0]
    return None


def ingest_repository(
    path: str | Path,
    allowed_roots: tuple[Path, ...],
    limits: Limits | None = None,
    *,
    home: Path | None = None,
) -> RepoSnapshot:
    """Load a repository into a :class:`RepoSnapshot` after enforcing the path policy."""
    limits = limits or Limits()
    root = resolve_repo_root(path, allowed_roots, home=home)
    files: dict[str, RepoFile] = {}
    excluded: list[Exclusion] = []
    total_bytes = 0

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        rel_dir = current.relative_to(root)
        kept_dirs = []
        for name in sorted(dirnames):
            rel = PurePosixPath(*rel_dir.parts, name).as_posix()
            if (current / name).is_symlink():
                excluded.append(Exclusion(rel + "/", "symlink"))
            elif name in IGNORED_DIR_NAMES or name.endswith(".egg-info"):
                excluded.append(Exclusion(rel + "/", "ignored-directory"))
            elif is_sensitive_path(rel + "/x"):
                excluded.append(Exclusion(rel + "/", "sensitive"))
            else:
                kept_dirs.append(name)
        dirnames[:] = kept_dirs

        for name in sorted(filenames):
            rel = PurePosixPath(*rel_dir.parts, name).as_posix()
            full = current / name
            # Sensitive files are skipped by name, before any byte is read.
            if is_sensitive_path(rel):
                excluded.append(Exclusion(rel, "sensitive"))
                continue
            if full.is_symlink():
                excluded.append(Exclusion(rel, "symlink"))
                continue
            if len(files) >= limits.max_files:
                excluded.append(Exclusion(rel, "file-count-limit"))
                continue
            data = _read_regular_file(full, limits.max_file_bytes)
            if isinstance(data, str):
                excluded.append(Exclusion(rel, data))
                continue
            if b"\x00" in data[:_BINARY_SNIFF_BYTES]:
                excluded.append(Exclusion(rel, "binary"))
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                excluded.append(Exclusion(rel, "not-utf8"))
                continue
            if total_bytes + len(data) > limits.max_total_bytes:
                excluded.append(Exclusion(rel, "total-size-limit"))
                continue
            total_bytes += len(data)
            files[rel] = RepoFile(rel, text, _sha256(data))

    digest = hashlib.sha256()
    for rel in sorted(files):
        digest.update(f"{rel}\0{files[rel].sha256}\n".encode())
    return RepoSnapshot(
        root=root,
        files=MappingProxyType(files),
        excluded=tuple(excluded),
        content_hash=digest.hexdigest(),
        git_head=read_git_head(root),
    )
