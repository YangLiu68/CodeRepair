"""Content-hash manifest for benchmark provenance and reproducibility."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..patch import apply_proposal
from ..repo import ingest_repository
from .tasks import TaskSpec

MANIFEST_SCHEMA = 1


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if "__pycache__" in rel.parts or path.name == ".DS_Store":
            continue
        digest.update(f"{rel.as_posix()}\0{_file_hash(path)}\n".encode())
    return digest.hexdigest()


def task_fingerprint(task: TaskSpec) -> dict[str, str]:
    return {
        "repo": tree_hash(task.repo_dir),
        "issue": _file_hash(task.issue_path),
        "solution": _file_hash(task.solution_path),
        "hidden_tests": tree_hash(task.hidden_tests_dir),
        "task_toml": _file_hash(task.dir / "task.toml"),
    }


def build_manifest(tasks: list[TaskSpec]) -> dict:
    return {
        "schema": MANIFEST_SCHEMA,
        "tasks": {task.id: task_fingerprint(task) for task in tasks},
    }


def check_manifest(tasks: list[TaskSpec], manifest_path: Path) -> list[str]:
    if not manifest_path.exists():
        return [f"{manifest_path} does not exist; run `coderepair build-fixtures`"]
    recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    current = build_manifest(tasks)
    problems = []
    for task_id in sorted(set(recorded.get("tasks", {})) | set(current["tasks"])):
        old = recorded.get("tasks", {}).get(task_id)
        new = current["tasks"].get(task_id)
        if old != new:
            changed = (
                sorted(k for k in (new or {}) if (old or {}).get(k) != new.get(k)) if new else []
            )
            problems.append(f"{task_id}: manifest mismatch {changed or '(task added/removed)'}")
    return problems


def write_solution_patch(task: TaskSpec) -> str:
    """Render solution.json as a unified diff for human review; returns the diff."""
    snapshot = ingest_repository(task.repo_dir, (task.dir,))
    result = apply_proposal(snapshot, task.load_solution())
    if not result.ok:
        raise ValueError(f"{task.id}: gold solution does not apply: {result.errors}")
    task.solution_patch_path.write_text(result.diff, encoding="utf-8")
    return result.diff


def write_manifest(tasks: list[TaskSpec], manifest_path: Path) -> None:
    manifest_path.write_text(json.dumps(build_manifest(tasks), indent=2) + "\n", encoding="utf-8")
