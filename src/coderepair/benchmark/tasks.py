"""Benchmark task registry.

Task layout (``benchmarks/tasks/<id>/``)::

    issue.md        agent-visible issue text
    repo/           agent-visible buggy repository (the only directory the agent can read)
    task.toml       harness-only metadata: category, fail-to-pass and pass-to-pass
                    test ids, provenance
    solution.json   harness-only gold edits (same schema as an agent proposal)
    solution.patch  harness-only unified diff rendered from solution.json
    hidden_tests/   harness-only held-out tests, copied into repo/tests/ at evaluation time

Only :meth:`TaskSpec.agent_view` crosses into the agent pipeline.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..patch import PatchProposal

# t01_... first-party fixtures, q01_... the public (QuixBugs-derived) suite
TASK_ID_RE = re.compile(r"^[tq]\d{2}_[a-z0-9_]+$")


class TaskError(ValueError):
    pass


@dataclass(frozen=True)
class TaskSpec:
    id: str
    dir: Path
    category: str
    difficulty: str
    issue_style: str
    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...]
    adversarial: tuple[str, ...]
    provenance: dict

    @property
    def repo_dir(self) -> Path:
        return self.dir / "repo"

    @property
    def issue_path(self) -> Path:
        return self.dir / "issue.md"

    @property
    def solution_path(self) -> Path:
        return self.dir / "solution.json"

    @property
    def solution_patch_path(self) -> Path:
        return self.dir / "solution.patch"

    @property
    def hidden_tests_dir(self) -> Path:
        return self.dir / "hidden_tests"

    def read_issue(self) -> str:
        return self.issue_path.read_text(encoding="utf-8")

    @property
    def title(self) -> str:
        for line in self.read_issue().splitlines():
            if line.strip():
                return line.strip().lstrip("#").strip()
        return self.id

    def load_solution(self) -> PatchProposal:
        """Harness-only: the gold edits. Never pass this to an agent backend."""
        return PatchProposal.model_validate_json(self.solution_path.read_text(encoding="utf-8"))

    def hidden_test_files(self) -> list[Path]:
        return sorted(self.hidden_tests_dir.glob("test_hidden_*.py"))

    def hidden_test_overlay(self) -> dict[str, str]:
        """Harness-only: hidden tests keyed by the path they take in the evaluated repo."""
        return {
            f"tests/{path.name}": path.read_text(encoding="utf-8")
            for path in self.hidden_test_files()
        }

    @property
    def expected_tests(self) -> frozenset[str]:
        return frozenset(self.fail_to_pass) | frozenset(self.pass_to_pass)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "difficulty": self.difficulty,
            "issue_style": self.issue_style,
            "adversarial": list(self.adversarial),
        }


def _load(task_dir: Path) -> TaskSpec:
    meta_path = task_dir / "task.toml"
    try:
        meta = tomllib.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise TaskError(f"{task_dir.name}: cannot read task.toml: {exc}") from exc
    if meta.get("id") != task_dir.name:
        raise TaskError(
            f"{task_dir.name}: task.toml id {meta.get('id')!r} does not match directory"
        )
    for key in (
        "category",
        "difficulty",
        "issue_style",
        "fail_to_pass",
        "pass_to_pass",
        "provenance",
    ):
        if key not in meta:
            raise TaskError(f"{task_dir.name}: task.toml is missing {key!r}")
    return TaskSpec(
        id=meta["id"],
        dir=task_dir,
        category=meta["category"],
        difficulty=meta["difficulty"],
        issue_style=meta["issue_style"],
        fail_to_pass=tuple(meta["fail_to_pass"]),
        pass_to_pass=tuple(meta["pass_to_pass"]),
        adversarial=tuple(meta.get("adversarial", ())),
        provenance=dict(meta["provenance"]),
    )


def list_tasks(tasks_dir: Path) -> list[TaskSpec]:
    if not tasks_dir.is_dir():
        raise TaskError(f"tasks directory not found: {tasks_dir}")
    return [
        _load(d) for d in sorted(tasks_dir.iterdir()) if d.is_dir() and TASK_ID_RE.match(d.name)
    ]


def load_any_task(task_dirs: tuple[Path, ...], task_id: str) -> TaskSpec:
    """Find ``task_id`` in any of the benchmark suites."""
    if not TASK_ID_RE.match(task_id):
        raise TaskError(f"invalid task id {task_id!r}")
    for tasks_dir in task_dirs:
        if (tasks_dir / task_id).is_dir():
            return _load(tasks_dir / task_id)
    raise TaskError(f"unknown task {task_id!r}")


def load_task(tasks_dir: Path, task_id: str) -> TaskSpec:
    if not TASK_ID_RE.match(task_id):
        raise TaskError(f"invalid task id {task_id!r}")
    task_dir = tasks_dir / task_id
    if not task_dir.is_dir():
        raise TaskError(f"unknown task {task_id!r}")
    return _load(task_dir)
