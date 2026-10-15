"""Prepare the throwaway directory a sandboxed run works in.

Layout of a run directory (created with mode 0700 under the system temp dir)::

    <root>/workspace/   repository files (exposed read-only to the sandbox)
    <root>/tmp/         writable scratch space ($HOME and $TMPDIR inside the sandbox)
    <root>/out/         writable; receives the results file

The workspace is written from an in-memory :class:`~coderepair.repo.RepoSnapshot`
plus the patch overlay, never copied from the live repository, so it contains
only files that passed ingestion (no symlinks, secrets, binaries or tool
directories) and the source repository is never touched.
"""

from __future__ import annotations

import os
import posixpath
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..repo import RepoSnapshot
from .base import SandboxError


@dataclass
class RunDir:
    root: Path
    workspace: Path
    tmp: Path
    out: Path

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> RunDir:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()


def _check_relpath(path: str) -> str:
    if not path or "\x00" in path or "\\" in path or path.startswith("/"):
        raise SandboxError(f"unsafe workspace path {path!r}")
    if posixpath.normpath(path) != path or ".." in PurePosixPath(path).parts:
        raise SandboxError(f"unsafe workspace path {path!r}")
    return path


def _write_new_file(root: Path, rel: str, text: str) -> None:
    target = root.joinpath(*PurePosixPath(_check_relpath(rel)).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target, flags, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def new_run_dir(prefix: str = "coderepair-sbx-") -> RunDir:
    # realpath: macOS temp dirs live behind the /var -> /private/var symlink, and the
    # Seatbelt profile matches resolved paths.
    root = Path(os.path.realpath(tempfile.mkdtemp(prefix=prefix)))
    workspace, tmp, out = root / "workspace", root / "tmp", root / "out"
    for d in (workspace, tmp, out):
        d.mkdir(mode=0o700)
    return RunDir(root, workspace, tmp, out)


def prepare_run_dir(
    snapshot: RepoSnapshot,
    *,
    overlay: Mapping[str, str] | None = None,
    extra_files: Mapping[str, str] | None = None,
) -> RunDir:
    """Write ``snapshot`` (with ``overlay`` edits and harness ``extra_files``) to a run dir.

    ``overlay`` may only replace files that exist in the snapshot (a validated
    patch). ``extra_files`` are harness-owned additions such as hidden tests and
    must not collide with repository files.
    """
    overlay = dict(overlay or {})
    extra_files = dict(extra_files or {})
    unknown = sorted(set(overlay) - set(snapshot.files))
    if unknown:
        raise SandboxError(f"patch overlay touches files outside the snapshot: {unknown}")
    clashes = sorted(set(extra_files) & set(snapshot.files))
    if clashes:
        raise SandboxError(f"harness files would overwrite repository files: {clashes}")
    run_dir = new_run_dir()
    try:
        for path in snapshot.paths():
            _write_new_file(run_dir.workspace, path, overlay.get(path, snapshot.text(path)))
        for path, text in sorted(extra_files.items()):
            _write_new_file(run_dir.workspace, path, text)
    except BaseException:
        run_dir.cleanup()
        raise
    return run_dir
