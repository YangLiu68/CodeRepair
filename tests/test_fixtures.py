"""Milestone 1 acceptance: the seeded-bug fixtures are valid and reproducible.

These tests run each fixture's own test suite (first-party code only) three times:
buggy visible tests, buggy + hidden tests, and gold + hidden tests.
"""

from __future__ import annotations

import json
import os
import shutil

import pytest
from helpers import ALL_TASK_IDS, TASKS_DIR

from coderepair.benchmark.manifest import check_manifest
from coderepair.benchmark.tasks import TaskError, list_tasks, load_task
from coderepair.benchmark.validate import UntrustedFixtureError, validate_task
from coderepair.config import PROJECT_ROOT


def test_there_are_ten_tasks_with_diverse_categories():
    tasks = list_tasks(TASKS_DIR)
    assert len(tasks) == 10
    assert len({t.category for t in tasks}) == 10
    assert any(t.adversarial for t in tasks)


@pytest.mark.parametrize("task_id", ALL_TASK_IDS)
def test_fixture_is_valid(task_id):
    report = validate_task(load_task(TASKS_DIR, task_id), trusted_root=TASKS_DIR)
    assert report.ok, report.problems
    assert report.counts["fail_to_pass"] >= 2
    assert report.counts["hidden_tests"] >= 2


def test_manifest_is_up_to_date():
    assert (
        check_manifest(list_tasks(TASKS_DIR), PROJECT_ROOT / "benchmarks" / "manifest.json") == []
    )


def test_task_ids_are_validated():
    for bad in ("../../etc", "t01", "T01_x", "t01_x/../../y"):
        with pytest.raises(TaskError):
            load_task(TASKS_DIR, bad)


# ------------------------------------------------------- validator catches bad fixtures


@pytest.fixture
def copied_task(tmp_path):
    root = tmp_path / "tasks"
    shutil.copytree(TASKS_DIR / "t01_paginate_off_by_one", root / "t01_paginate_off_by_one")
    return root, load_task(root, "t01_paginate_off_by_one")


def test_validator_refuses_untrusted_roots(copied_task, tmp_path):
    _, spec = copied_task
    with pytest.raises(UntrustedFixtureError):
        validate_task(spec, trusted_root=tmp_path / "somewhere-else")


def test_validator_refuses_symlinks(copied_task):
    root, spec = copied_task
    os.symlink("/etc/hosts", spec.repo_dir / "hosts")
    with pytest.raises(UntrustedFixtureError, match="symlink"):
        validate_task(spec, trusted_root=root)


def test_validator_detects_a_gold_patch_that_does_not_fix_the_bug(copied_task):
    root, spec = copied_task
    solution = json.loads(spec.solution_path.read_text())
    solution["edits"][0]["new"] = "    start = page * per_page  # no-op\n"
    spec.solution_path.write_text(json.dumps(solution))
    spec.solution_patch_path.unlink()
    report = validate_task(spec, trusted_root=root)
    assert not report.ok
    assert any("gold repo" in p and "expected passed" in p for p in report.problems)
    assert any("solution.patch missing" in p for p in report.problems)


def test_validator_detects_a_wrong_fail_to_pass_list(copied_task):
    root, spec = copied_task
    toml = (spec.dir / "task.toml").read_text()
    (spec.dir / "task.toml").write_text(
        toml.replace(
            '"tests/test_core.py::test_first_page_starts_at_first_item",',
            '"tests/test_core.py::test_total_pages_rounds_up",',
        )
    )
    report = validate_task(load_task(root, spec.id), trusted_root=root)
    assert not report.ok
    assert any("test_total_pages_rounds_up passed, expected failed" in p for p in report.problems)
    assert any(
        "test_first_page_starts_at_first_item failed, expected passed" in p for p in report.problems
    )


def test_validator_detects_hidden_tests_that_miss_the_bug(copied_task):
    root, spec = copied_task
    hidden = spec.hidden_tests_dir / "test_hidden_pager.py"
    hidden.write_text("def test_hidden_trivial():\n    assert True\n")
    toml = (spec.dir / "task.toml").read_text()
    lines = [line for line in toml.splitlines() if "test_hidden_pager.py" not in line]
    (spec.dir / "task.toml").write_text("\n".join(lines) + "\n")
    report = validate_task(load_task(root, spec.id), trusted_root=root)
    assert "no hidden test detects the bug" in report.problems
