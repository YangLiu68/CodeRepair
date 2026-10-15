"""Validate first-party benchmark fixtures by running their tests.

SECURITY NOTE: this is the one place where repository code runs on the host.
It is allowed only for first-party fixtures that live under an explicitly trusted
root (``benchmarks/tasks`` in this project), runs on a throwaway copy, with a
scrubbed environment, ``HOME``/``TMPDIR`` pointed at a temp dir, third-party
pytest plugin autoloading disabled, and a timeout. Untrusted repositories are
executed only inside the Milestone 2 sandbox, never through this module.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..patch import apply_proposal
from ..repo import ingest_repository
from .tasks import TaskSpec

RESULTS_PLUGIN = "coderepair.benchmark.pytest_results"


class UntrustedFixtureError(PermissionError):
    pass


@dataclass
class TestRun:
    label: str
    outcomes: dict[str, str]
    collect_errors: list[str]
    exitstatus: int
    duration_s: float
    output_tail: str = ""


@dataclass
class TaskValidation:
    task_id: str
    problems: list[str] = field(default_factory=list)
    runs: dict[str, TestRun] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems


def _assert_trusted(task: TaskSpec, trusted_root: Path) -> None:
    root = trusted_root.resolve()
    task_dir = task.dir.resolve()
    if root not in task_dir.parents:
        raise UntrustedFixtureError(f"{task_dir} is not under the trusted fixture root {root}")
    for path in task.dir.rglob("*"):
        if path.is_symlink():
            raise UntrustedFixtureError(f"fixtures must not contain symlinks: {path}")


def _scrubbed_env(home: Path, results_path: Path) -> dict[str, str]:
    return {
        "PATH": os.pathsep.join([str(Path(sys.executable).parent), "/usr/bin", "/bin"]),
        "HOME": str(home),
        "TMPDIR": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "NO_COLOR": "1",
        "CODEREPAIR_RESULTS_PATH": str(results_path),
    }


def run_fixture_tests(workdir: Path, label: str, timeout_s: int) -> TestRun:
    scratch = Path(tempfile.mkdtemp(prefix="coderepair-home-"))
    results_path = scratch / "results.json"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        RESULTS_PLUGIN,
        "-p",
        "no:cacheprovider",
        "-q",
        "--color=no",
    ]
    start = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, trusted first-party fixture only
            cmd,
            cwd=workdir,
            env=_scrubbed_env(scratch, results_path),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        duration = time.monotonic() - start
        output = (proc.stdout + proc.stderr)[-4000:]
        if not results_path.exists():
            return TestRun(label, {}, ["<no results written>"], proc.returncode, duration, output)
        data = json.loads(results_path.read_text(encoding="utf-8"))
        return TestRun(
            label, data["tests"], data["collect_errors"], data["exitstatus"], duration, output
        )
    except subprocess.TimeoutExpired:
        return TestRun(label, {}, ["<timeout>"], -1, time.monotonic() - start, "")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def materialize(task: TaskSpec, dest: Path, *, gold: bool, hidden: bool) -> Path:
    """Copy the buggy repo to ``dest``, optionally applying gold edits and hidden tests."""
    shutil.copytree(
        task.repo_dir, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache")
    )
    if gold:
        snapshot = ingest_repository(task.repo_dir, (task.dir,))
        result = apply_proposal(snapshot, task.load_solution())
        if not result.ok:
            raise ValueError(f"gold solution does not apply: {result.errors}")
        for rel, text in result.changed_files.items():
            (dest / rel).write_text(text, encoding="utf-8")
    if hidden:
        for test_file in task.hidden_test_files():
            shutil.copy2(test_file, dest / "tests" / test_file.name)
    return dest


def _check_structure(task: TaskSpec) -> list[str]:
    problems = []
    for required in (task.repo_dir, task.issue_path, task.solution_path, task.hidden_tests_dir):
        if not required.exists():
            problems.append(f"missing {required.name}")
    if problems:
        return problems
    if not task.hidden_test_files():
        problems.append("hidden_tests/ has no test_hidden_*.py files")
    for visible in task.repo_dir.rglob("test_hidden_*.py"):
        problems.append(f"visible repo must not contain hidden-test names: {visible.name}")
    for path in task.dir.rglob("*"):
        if path.is_file() and path.name not in {".DS_Store"} and "__pycache__" not in path.parts:
            if path.parent == task.dir and path.name not in {
                "issue.md",
                "task.toml",
                "solution.json",
                "solution.patch",
            }:
                problems.append(f"unexpected file in task directory: {path.name}")
    return problems


def validate_task(task: TaskSpec, *, trusted_root: Path, timeout_s: int = 120) -> TaskValidation:
    """Check that a fixture is a well-formed, reproducible seeded-bug task."""
    _assert_trusted(task, trusted_root)
    report = TaskValidation(task.id)
    report.problems.extend(_check_structure(task))
    if report.problems:
        return report

    snapshot = ingest_repository(task.repo_dir, (task.dir,))
    gold = apply_proposal(snapshot, task.load_solution())
    if not gold.ok:
        report.problems.append(f"gold solution violates the patch policy: {gold.errors}")
        return report
    if task.solution_patch_path.exists():
        if task.solution_patch_path.read_text(encoding="utf-8") != gold.diff:
            report.problems.append("solution.patch is stale; run `coderepair build-fixtures`")
    else:
        report.problems.append("solution.patch missing; run `coderepair build-fixtures`")

    with tempfile.TemporaryDirectory(prefix=f"coderepair-{task.id}-") as tmp:
        tmp_path = Path(tmp)
        runs = {
            "buggy_visible": materialize(task, tmp_path / "bv", gold=False, hidden=False),
            "buggy_all": materialize(task, tmp_path / "ba", gold=False, hidden=True),
            "gold_all": materialize(task, tmp_path / "ga", gold=True, hidden=True),
        }
        for label, workdir in runs.items():
            report.runs[label] = run_fixture_tests(workdir, label, timeout_s)

    collection_problems = [
        f"{label}: collection errors {run.collect_errors}"
        for label, run in report.runs.items()
        if run.collect_errors
    ]
    if collection_problems:
        report.problems.extend(collection_problems)
        return report

    f2p = set(task.fail_to_pass)
    buggy_vis, buggy_all, gold_all = (
        report.runs["buggy_visible"],
        report.runs["buggy_all"],
        report.runs["gold_all"],
    )
    hidden_ids = {t for t in buggy_all.outcomes if "/test_hidden_" in t}
    missing = sorted(f2p - set(buggy_all.outcomes))
    if missing:
        report.problems.append(f"fail_to_pass ids not collected: {missing}")
    for test_id, outcome in sorted(buggy_all.outcomes.items()):
        expected = "failed" if test_id in f2p else "passed"
        if outcome != expected:
            report.problems.append(f"buggy repo: {test_id} {outcome}, expected {expected}")
    for test_id, outcome in sorted(buggy_vis.outcomes.items()):
        expected = "failed" if test_id in f2p else "passed"
        if outcome != expected:
            report.problems.append(
                f"buggy repo (visible only): {test_id} {outcome}, expected {expected}"
            )
    for test_id, outcome in sorted(gold_all.outcomes.items()):
        if outcome != "passed":
            report.problems.append(f"gold repo: {test_id} {outcome}, expected passed")
    if set(gold_all.outcomes) != set(buggy_all.outcomes):
        report.problems.append("buggy and gold runs collected different tests")
    if not (f2p & hidden_ids):
        report.problems.append("no hidden test detects the bug")

    report.counts = {
        "visible_tests": len(buggy_vis.outcomes),
        "hidden_tests": len(hidden_ids),
        "fail_to_pass": len(f2p),
        "visible_fail_to_pass": len(f2p - hidden_ids),
        "pass_to_pass": len(buggy_all.outcomes) - len(f2p),
    }
    return report
