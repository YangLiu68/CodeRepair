from __future__ import annotations

from pathlib import Path

from coderepair.benchmark.tasks import TaskSpec, list_tasks, load_task
from coderepair.config import PROJECT_ROOT
from coderepair.repo import RepoSnapshot, ingest_repository

TASKS_DIR = PROJECT_ROOT / "benchmarks" / "tasks"
DEMO_DIR = PROJECT_ROOT / "docs" / "demo"
ALL_TASK_IDS = [t.id for t in list_tasks(TASKS_DIR)]


def task(task_id: str) -> TaskSpec:
    return load_task(TASKS_DIR, task_id)


def snapshot_of(task_id: str) -> RepoSnapshot:
    return ingest_repository(task(task_id).repo_dir, (TASKS_DIR,))


def make_repo(root: Path, files: dict[str, str | bytes]) -> Path:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return root
