"""Milestone 6: the public task subset (derived from QuixBugs, MIT License).

The upstream programs are third-party code, so every execution here goes
through a sandbox; tests that need one are skipped (with the reason) where no
sandbox backend is available.
"""

from __future__ import annotations

import json
import tomllib

import pytest

from coderepair.agent import propose_patch
from coderepair.benchmark.manifest import check_manifest
from coderepair.benchmark.tasks import list_tasks
from coderepair.benchmark.validate import SandboxFixtureRunner, validate_task
from coderepair.config import PROJECT_ROOT
from coderepair.llm.scripted import ScriptedBackend
from coderepair.repo import ingest_repository
from coderepair.sandbox.base import SandboxLimits

PUBLIC = PROJECT_ROOT / "benchmarks" / "public"
PUBLIC_TASKS = list_tasks(PUBLIC)
PUBLIC_IDS = [t.id for t in PUBLIC_TASKS]
BY_ID = {t.id: t for t in PUBLIC_TASKS}


def test_public_suite_size_license_and_provenance():
    assert len(PUBLIC_TASKS) == 12
    license_text = (PUBLIC / "LICENSE-QuixBugs.txt").read_text()
    assert "Copyright 2017-2019 James Koppel" in license_text
    assert "Permission is hereby granted, free of charge" in license_text
    for task in PUBLIC_TASKS:
        provenance = tomllib.loads((task.dir / "task.toml").read_text())["provenance"]
        assert provenance["source"] == "https://github.com/jkoppel/QuixBugs"
        assert len(provenance["source_commit"]) == 40
        assert provenance["license"].startswith("MIT")


def test_public_manifest_is_up_to_date():
    assert check_manifest(PUBLIC_TASKS, PUBLIC / "manifest.json") == []


@pytest.mark.parametrize("task_id", PUBLIC_IDS)
def test_agent_visible_material_has_no_upstream_traces(task_id):
    """No corrected code, upstream test harness or dataset name reaches the agent."""
    task = BY_ID[task_id]
    snapshot = ingest_repository(task.repo_dir, (PUBLIC,))
    visible = "\n".join(snapshot.text(p) for p in snapshot.paths()) + task.read_issue()
    for marker in ("QuixBugs", "quixbugs", "correct_python_programs", "load_testdata"):
        assert marker not in visible
    gold_added = {
        line.strip()
        for edit in task.load_solution().edits
        for line in edit.new.splitlines()
        if line.strip() and line.strip() not in edit.old
    }
    assert gold_added, "every public task changes at least one line"
    backend = ScriptedBackend([json.dumps({"summary": "", "edits": []})])
    propose_patch(snapshot, task.read_issue(), backend, task_id=task.id)
    prompt = backend.requests[0].user
    for line in gold_added:
        assert line not in prompt, line
    assert "test_hidden_" not in prompt


@pytest.mark.parametrize("task_id", PUBLIC_IDS)
def test_public_task_is_valid_in_the_sandbox(sandbox, task_id):
    report = validate_task(
        BY_ID[task_id],
        trusted_root=PUBLIC,
        runner=SandboxFixtureRunner(sandbox, SandboxLimits()),
    )
    assert report.ok, report.problems


def test_public_suite_never_runs_on_the_host(monkeypatch):
    """validate-fixtures runs the third-party programs only through a sandbox."""
    import coderepair.benchmark.validate as validate
    from coderepair.cli import main

    def forbidden(self, *args, **kwargs):
        raise AssertionError("third-party code would run on the host")

    monkeypatch.setattr(validate.HostFixtureRunner, "__call__", forbidden)
    # 0 with a sandbox; 2 ("no sandbox available") on machines without one.
    assert main(["validate-fixtures", "--suite", "public", PUBLIC_IDS[0]]) in (0, 2)


@pytest.mark.parametrize("task_id", PUBLIC_IDS)
def test_issue_never_quotes_a_hidden_test_case(task_id):
    """The issue's example must not be one of the held-out cases (review finding)."""
    import ast

    task = BY_ID[task_id]
    name = task_id.split("_", 1)[1]
    issue = task.read_issue()
    for hidden in task.hidden_test_files():
        for node in ast.walk(ast.parse(hidden.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "param":
                args = ast.literal_eval(node.args[0])
                call = f"{name}({', '.join(json.dumps(a) for a in args)})"
                assert call not in issue, f"{task_id}: issue quotes hidden case {call}"
