"""The runner bundle: the only third-party code made available inside a sandbox.

The bundle is a directory holding pytest and its pure-Python dependencies,
copied file by file from the locked environment CodeRepair runs in, plus a
small bootstrap script and the results plugin. Both sandbox backends expose it
read-only, so the container image needs nothing but a stock Python and no
packages are downloaded at test time. The directory name is a content hash,
so a changed environment produces a new bundle instead of mutating one.
"""

from __future__ import annotations

import hashlib
import importlib.metadata as md
import os
import shutil
import tempfile
from pathlib import Path

BUNDLE_DISTRIBUTIONS = ("pytest", "pluggy", "iniconfig", "packaging", "pygments")
_NATIVE_SUFFIXES = (".so", ".dylib", ".pyd", ".dll")
_PLUGIN_SOURCE = Path(__file__).resolve().parent.parent / "benchmark" / "pytest_results.py"

BOOTSTRAP = '''\
"""CodeRepair sandbox bootstrap: run pytest with an explicit, minimal sys.path.

Started as ``python -I -S -B bootstrap.py <pytest args>``: isolated mode, no
site-packages, no bytecode writes. The bundle comes first on sys.path so the
repository cannot shadow pytest; the working directory (the repository) is
added after pytest has been imported.
"""
import os
import sys

_bundle = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _bundle)
import pytest  # noqa: E402

sys.path.insert(1, os.getcwd())
sys.exit(pytest.main(sys.argv[1:]))
'''


class BundleError(RuntimeError):
    pass


def _distribution_files(name: str) -> list[tuple[str, Path]]:
    try:
        dist = md.distribution(name)
    except md.PackageNotFoundError as exc:
        raise BundleError(f"{name} is not installed in this environment") from exc
    files = []
    for entry in dist.files or []:
        rel = str(entry)
        if rel.startswith("..") or "__pycache__" in rel or rel.endswith((".pyc", ".pyo")):
            continue
        if rel.endswith(_NATIVE_SUFFIXES):
            raise BundleError(f"{name} ships native code ({rel}); the bundle must be pure Python")
        source = Path(entry.locate())
        if source.is_file():
            files.append((rel, source))
    if not files:
        raise BundleError(f"no files found for distribution {name}")
    return files


def bundle_contents() -> dict[str, bytes]:
    """Every file of the bundle, keyed by its relative path."""
    contents: dict[str, bytes] = {}
    for name in BUNDLE_DISTRIBUTIONS:
        for rel, source in _distribution_files(name):
            contents[rel] = source.read_bytes()
    contents["bootstrap.py"] = BOOTSTRAP.encode()
    contents["coderepair_results.py"] = _PLUGIN_SOURCE.read_bytes()
    return contents


def bundle_digest(contents: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for rel in sorted(contents):
        digest.update(rel.encode() + b"\0" + hashlib.sha256(contents[rel]).digest())
    return digest.hexdigest()


def _is_complete(target: Path, digest: str) -> bool:
    marker = target / ".complete"
    return marker.is_file() and marker.read_text(encoding="utf-8") == digest


def _force_rmtree(path: Path) -> None:
    if not path.exists():
        return
    for p in [path, *path.rglob("*")]:
        if p.is_dir() and not p.is_symlink():
            p.chmod(0o700)
    shutil.rmtree(path, ignore_errors=True)


def ensure_runner_bundle(cache_dir: Path) -> Path:
    """Return the bundle directory for the current environment, building it if needed."""
    contents = bundle_contents()
    digest = bundle_digest(contents)
    cache_dir = Path(os.path.realpath(cache_dir))
    target = cache_dir / f"runner-{digest[:16]}"
    if _is_complete(target, digest):
        return target
    cache_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".runner-staging-", dir=cache_dir))
    try:
        for rel, data in contents.items():
            path = staging / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(0o444)
        (staging / ".complete").write_text(digest, encoding="utf-8")
        for d in [staging, *(p for p in staging.rglob("*") if p.is_dir())]:
            d.chmod(0o755)
        if target.exists() and not _is_complete(target, digest):
            _force_rmtree(target)  # left behind by an interrupted build
        try:
            os.rename(staging, target)
        except OSError:
            if not _is_complete(target, digest):  # lost a race with a broken build
                raise
    finally:
        _force_rmtree(staging)
    return target
