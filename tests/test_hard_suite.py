"""The hard tier: tasks are built from one base repository and validate like the fixtures."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from coderepair.agent import STATUS_PROPOSED, propose_patch
from coderepair.benchmark.hard_suite import build_task, check_built, load_bug, seed_bug
from coderepair.benchmark.manifest import check_manifest
from coderepair.benchmark.oracle import OracleBackend
from coderepair.benchmark.tasks import TaskError, list_tasks, load_task
from coderepair.benchmark.validate import run_fixture_tests, validate_task
from coderepair.cli import _suites
from coderepair.config import PROJECT_ROOT
from coderepair.issue import parse_issue
from coderepair.llm.scripted import ScriptedBackend
from coderepair.prompting import build_direct_prompt
from coderepair.repo import ingest_repository

HARD = PROJECT_ROOT / "benchmarks" / "hard"
SOURCES = PROJECT_ROOT / "benchmarks" / "hard_src"
HARD_IDS = [t.id for t in list_tasks(HARD)]


def test_nine_tasks_with_distinct_categories():
    tasks = list_tasks(HARD)
    assert len(tasks) == 9
    assert len({t.category for t in tasks}) == 9
    assert all(t.id.startswith("h") for t in tasks)


def test_built_tasks_match_their_sources():
    assert check_built(SOURCES, HARD) == []


def test_manifest_is_up_to_date():
    assert check_manifest(list_tasks(HARD), HARD / "manifest.json") == []


@pytest.mark.parametrize("task_id", HARD_IDS)
def test_hard_task_is_valid(task_id):
    report = validate_task(load_task(HARD, task_id), trusted_root=HARD)
    assert report.ok, report.problems
    assert report.counts["hidden_tests"] >= 3
    assert report.counts["fail_to_pass"] >= 2


def test_the_base_repository_passes_its_own_tests():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "base"
        shutil.copytree(SOURCES / "base", work, ignore=shutil.ignore_patterns("__pycache__"))
        run = run_fixture_tests(work, "base", timeout_s=120)
    assert run.collect_errors == []
    assert run.outcomes and set(run.outcomes.values()) == {"passed"}


@pytest.mark.parametrize("task_id", HARD_IDS)
def test_oracle_pipeline_reproduces_the_gold_diff(task_id):
    spec = load_task(HARD, task_id)
    snapshot = ingest_repository(spec.repo_dir, (HARD,))
    run = propose_patch(snapshot, spec.read_issue(), OracleBackend(spec), task_id=task_id)
    assert run.status == STATUS_PROPOSED, run.errors
    assert run.diff == spec.solution_patch_path.read_text()


@pytest.mark.parametrize("task_id", HARD_IDS)
def test_prompts_contain_no_solution_or_hidden_test_content(task_id):
    spec = load_task(HARD, task_id)
    snapshot = ingest_repository(spec.repo_dir, (HARD,))
    visible = "\n".join(snapshot.text(p) for p in snapshot.paths()) + "\n" + spec.read_issue()
    gold = {line.strip() for e in spec.load_solution().edits for line in e.new.splitlines()}
    hidden = {line.strip() for f in spec.hidden_test_files() for line in f.read_text().splitlines()}
    secrets = [g for g in gold if len(g) >= 8 and g not in visible]
    secrets += [h for h in hidden if len(h) >= 12 and h not in visible]
    assert secrets  # the check is not vacuous
    backend = ScriptedBackend(['{"summary": "", "edits": []}'])
    propose_patch(snapshot, spec.read_issue(), backend, task_id=task_id)
    direct = build_direct_prompt(snapshot, parse_issue(spec.read_issue())).request
    for prompt in (backend.requests[0].user, direct.user):
        for line in secrets:
            assert line not in prompt
        assert "test_hidden_" not in prompt and str(spec.dir) not in prompt


def test_gold_solutions_are_the_inverse_of_the_seeded_bugs():
    for task in list_tasks(HARD):
        bug = load_bug(SOURCES / "tasks" / task.id / "bug.json")
        gold = json.loads(task.solution_path.read_text())["edits"]
        assert gold == [{"path": e["path"], "old": e["new"], "new": e["old"]} for e in bug]


# ------------------------------------------------------------------ builder safeguards


def _source(tmp_path: Path, name: str, edits: list[dict], fail_to_pass: list[str]) -> Path:
    source = tmp_path / "tasks" / name
    source.mkdir(parents=True)
    (source / "bug.json").write_text(json.dumps(edits))
    (source / "issue.md").write_text("# issue\n")
    (source / "test_hidden_x.py").write_text(
        "from billing.money import Money\n\n\ndef test_hidden_split():\n"
        "    assert Money.of('-1.00', 'USD').split(3)[0] == Money.of('-0.34', 'USD')\n"
    )
    (source / "task.toml").write_text(
        'category = "c"\ndifficulty = "d"\nissue_style = "s"\nsummary = "x"\nseeded_bug = "y"\n'
        f"fail_to_pass = {json.dumps(fail_to_pass)}\n"
    )
    return source


H02_EDITS = load_bug(SOURCES / "tasks" / "h02_credit_allocation_sign" / "bug.json")


def test_builder_refuses_undeclared_failures(tmp_path):
    source = _source(tmp_path, "h90_sample", H02_EDITS, [])
    with pytest.raises(TaskError, match="unexpected"):
        build_task(source, SOURCES / "base", tmp_path / "out")


def test_builder_writes_pass_to_pass_from_a_real_run(tmp_path):
    source = _source(
        tmp_path, "h90_sample", H02_EDITS, ["tests/test_hidden_x.py::test_hidden_split"]
    )
    task = load_task(tmp_path / "out", build_task(source, SOURCES / "base", tmp_path / "out").name)
    assert task.fail_to_pass == ("tests/test_hidden_x.py::test_hidden_split",)
    assert "tests/test_money.py::test_allocate_adds_up_and_prefers_largest_remainders" in (
        task.pass_to_pass
    )


def test_seeding_needs_a_unique_anchor(tmp_path):
    edits = [{"path": "billing/money.py", "old": "import", "new": "# import"}]
    with pytest.raises(TaskError, match="found"):
        seed_bug(SOURCES / "base", tmp_path / "repo", edits)
    with pytest.raises(TaskError):
        bad = tmp_path / "bug.json"
        bad.write_text(json.dumps([{"path": "x", "old": "a", "new": "a"}]))
        load_bug(bad)


def test_builder_refuses_non_hard_ids(tmp_path):
    source = _source(tmp_path, "t90_sample", H02_EDITS, [])
    with pytest.raises(TaskError, match="h01_name"):
        build_task(source, SOURCES / "base", tmp_path / "out")


def test_suite_option():
    assert _suites("all") == ["fixtures", "public", "hard"]
    assert _suites("fixtures,public") == ["fixtures", "public"]
    assert _suites("hard,hard") == ["hard"]
    for bad in ("", "nope", "fixtures,nope"):
        with pytest.raises(argparse.ArgumentTypeError):
            _suites(bad)
