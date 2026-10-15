"""Milestone 4: static checks, security review, candidates, reproduction tests, approval."""

from __future__ import annotations

import json
import shutil

import pytest
from helpers import TASKS_DIR, snapshot_of, task

from coderepair.approval import (
    APPROVAL_FILE,
    ApprovalError,
    apply_approved,
    approve,
    load_approval,
)
from coderepair.candidates import REPRO_FAILED, REPRO_VERIFIED, check_repro_code
from coderepair.checks import lint_delta, security_review, typecheck_delta
from coderepair.cli import main
from coderepair.llm.scripted import ScriptedBackend
from coderepair.loop import LOOP_FIXED, LOOP_UNVERIFIED, RepairBudget, repair
from coderepair.repo import ingest_repository
from coderepair.security import PolicyError

T07 = "t07_safe_join_prefix_escape"
T07_RAISE = '        raise UnsafePathError(f"path escapes base directory: {parts!r}")\n'


def _t07_with(new_block: str) -> dict[str, str]:
    source = snapshot_of(T07).text("filestore/paths.py")
    assert T07_RAISE in source
    return {"filestore/paths.py": source.replace(T07_RAISE, new_block)}


# ------------------------------------------------------------------ static checks


def test_gold_patches_introduce_no_lint_type_or_security_findings():
    for task_id in ("t03_interval_merge_unsorted", T07, "t08_money_half_up"):
        from coderepair.patch import apply_proposal

        snapshot = snapshot_of(task_id)
        changed = apply_proposal(snapshot, task(task_id).load_solution()).changed_files
        assert lint_delta(snapshot, changed).status == "ok"
        assert typecheck_delta(snapshot, changed).status == "ok"
        assert security_review(snapshot, changed) == []


def test_checks_report_only_newly_introduced_problems():
    snapshot = snapshot_of(T07)
    changed = _t07_with("        undefined_helper()\n        unused = 1\n")
    lint = lint_delta(snapshot, changed)
    assert lint.status == "new-issues"
    assert sorted(d.code for d in lint.new) == ["F821", "F841"]
    types = typecheck_delta(snapshot, changed)
    assert types.status == "new-issues" and [d.code for d in types.new] == ["name-defined"]


def test_missing_tool_is_reported_as_skipped_not_passed(monkeypatch):
    import coderepair.checks as checks

    monkeypatch.setattr(checks, "_ruff_binary", lambda: None)
    monkeypatch.setattr(checks, "_mypy_available", lambda: False)
    snapshot = snapshot_of(T07)
    assert lint_delta(snapshot, _t07_with("        pass\n")).status == "skipped"
    assert typecheck_delta(snapshot, _t07_with("        pass\n")).status == "skipped"


def test_checks_never_execute_repository_code(tmp_path):
    marker = tmp_path / "executed"
    snapshot = snapshot_of(T07)
    payload = f"import pathlib\npathlib.Path({str(marker)!r}).write_text('x')\n"
    changed = {"filestore/__init__.py": payload + snapshot.text("filestore/__init__.py")}
    lint_delta(snapshot, changed)
    typecheck_delta(snapshot, changed)
    assert not marker.exists()


@pytest.mark.parametrize(
    "block, rule",
    [
        ("        import subprocess\n        subprocess.run(['ls'])\n", "process-execution"),
        ("        import os as o\n        o.system('id')\n", "process-execution"),
        ("        eval(parts[0])\n", "dynamic-code"),
        ("        import pickle\n        pickle.loads(b'')\n", "unsafe-deserialization"),
        ("        import yaml\n        yaml.load(parts[0])\n", "unsafe-deserialization"),
        ("        from urllib.request import urlopen\n        urlopen('http://x')\n", "network"),
        ("        open(base).close()\n        fn(shell=True)\n", "shell-injection"),
        ("        get(url, verify=False)\n", "tls-verification-disabled"),
        ("        import shutil\n        shutil.rmtree(base)\n", "filesystem-destruction"),
        ("        pass\n", "removed-validation"),
        ('        token = "ghp_' + "a" * 36 + '"\n', "hard-coded-secret"),
    ],
)
def test_security_review_flags_new_risky_constructs(block, rule):
    if rule != "removed-validation":
        block = T07_RAISE + block
    findings = security_review(snapshot_of(T07), _t07_with(block))
    assert rule in {f.rule for f in findings}, findings


def test_security_review_ignores_constructs_that_already_existed():
    snapshot = snapshot_of(T07)
    source = snapshot.text("filestore/paths.py")
    # Re-ordering existing code adds nothing new.
    changed = {"filestore/paths.py": source.replace("import os\n", "import os  # paths\n")}
    assert security_review(snapshot, changed) == []


# ------------------------------------------------------------- reproduction tests


@pytest.mark.parametrize(
    "code, problem",
    [
        ("def helper():\n    pass\n", "no top-level test functions"),
        ("import subprocess\n\ndef test_x():\n    pass\n", "subprocess"),
        ("import os\n\ndef test_x():\n    os.system('id')\n", ".system"),
        ("def test_x():\n    eval('1')\n", "eval"),
        ("import numpy\n\ndef test_x():\n    pass\n", "numpy"),
        ("from . import x\n\ndef test_x():\n    pass\n", "relative imports"),
        ("def test_x(:\n", "not valid Python"),
        ("def test_x():\n    pass\n" + "#" * 9000, "longer than"),
    ],
)
def test_reproduction_test_policy(code, problem):
    assert problem in (check_repro_code(code, snapshot_of("t02_mutable_default_tags")) or "")


def test_reproduction_test_may_import_the_repository_and_stdlib():
    code = "import json\nimport pytest\nfrom notes.models import Note\n\ndef test_x():\n    pass\n"
    assert check_repro_code(code, snapshot_of("t02_mutable_default_tags")) is None


T02_GOLD = task("t02_mutable_default_tags").solution_path.read_text(encoding="utf-8")
T02_REPRO = json.dumps(
    {
        "summary": "default tags are shared",
        "test_code": (
            "from notes.models import Note\n\n\n"
            "def test_default_tags_are_not_shared():\n"
            "    first = Note('a')\n"
            "    first.add_tag('x')\n"
            "    assert Note('b').tags == []\n"
        ),
    }
)
T02_NOOP = json.dumps(
    {
        "summary": "cosmetic",
        "edits": [
            {
                "path": "notes/models.py",
                "old": "        self.tags = tags\n",
                "new": "        self.tags = tags  # tags\n",
            }
        ],
    }
)


def _t02_repair(responses, sandbox, runs_dir=None, **budget):
    t = task("t02_mutable_default_tags")
    backend = ScriptedBackend(list(responses))
    run = repair(
        snapshot_of(t.id),
        t.read_issue(),
        backend,
        sandbox,
        budget=RepairBudget(**budget),
        runs_dir=runs_dir,
        task_id=t.id,
    )
    return run, backend


def test_reproduction_test_verifies_an_issue_only_task(sandbox):
    """t02 has no failing visible test; the generated reproduction test supplies one."""
    run, _ = _t02_repair([T02_GOLD, T02_REPRO], sandbox, repro_test=True)
    assert run.repro.status == "reproduces"
    assert run.selected.repro == REPRO_VERIFIED
    assert run.status == LOOP_FIXED


def test_candidates_are_ranked_by_reproduction_test(sandbox):
    # The loop accepts the no-op (visible tests already pass), a sample adds the real fix,
    # and the reproduction test separates them.
    run, _ = _t02_repair([T02_NOOP, T02_GOLD, T02_REPRO], sandbox, candidates=2, repro_test=True)
    assert [c.candidate.source for c in run.scorecards] == ["sample 1", "loop attempt 1"]
    assert [c.repro for c in run.scorecards] == [REPRO_VERIFIED, REPRO_FAILED]
    assert run.status == LOOP_FIXED and "[] if tags is None" in run.diff


def test_without_reproduction_test_issue_only_fix_is_unverified(sandbox):
    run, _ = _t02_repair([T02_NOOP], sandbox)
    assert run.status == LOOP_UNVERIFIED


def test_reproduction_test_that_passes_on_original_code_is_discarded(sandbox):
    code = "from notes.models import Note\n\ndef test_x():\n    assert Note('a')\n"
    passing = json.dumps({"summary": "x", "test_code": code})
    run, _ = _t02_repair([T02_GOLD, passing], sandbox, repro_test=True)
    assert run.repro.status == "does-not-reproduce"
    assert run.status == LOOP_UNVERIFIED


# ----------------------------------------------------------------------- approval


@pytest.fixture
def approved_setup(sandbox, tmp_path, monkeypatch):
    """A repair run on a private copy of t01 under its own allowed root."""
    repos = tmp_path / "repos"
    shutil.copytree(task("t01_paginate_off_by_one").repo_dir, repos / "pager")
    snapshot = ingest_repository(repos / "pager", (repos,))
    t = task("t01_paginate_off_by_one")
    run = repair(
        snapshot,
        t.read_issue(),
        ScriptedBackend([t.solution_path.read_text(encoding="utf-8")]),
        sandbox,
        runs_dir=tmp_path / "runs",
    )
    assert run.status == LOOP_FIXED
    return run, repos


def test_approve_then_apply_writes_only_the_approved_change(approved_setup):
    run, repos = approved_setup
    record = approve(run.run_dir, candidate=None, reviewer="alice")
    assert record.candidate == 1 and record.reviewer == "alice"
    assert oct((run.run_dir / APPROVAL_FILE).stat().st_mode & 0o777) == "0o600"
    before = {p: p.read_bytes() for p in (repos / "pager").rglob("*") if p.is_file()}
    result = apply_approved(run.run_dir, repos / "pager", allowed_roots=(repos,))
    assert result.written == ["pager/core.py"]
    after = {p: p.read_bytes() for p in (repos / "pager").rglob("*") if p.is_file()}
    changed = [p.name for p in before if before[p] != after[p]]
    assert changed == ["core.py"]
    assert b"(page - 1) * per_page" in after[repos / "pager" / "pager" / "core.py"]


def test_apply_requires_approval_and_refuses_changed_repos(approved_setup):
    run, repos = approved_setup
    with pytest.raises(ApprovalError, match="not been approved"):
        apply_approved(run.run_dir, repos / "pager", allowed_roots=(repos,))
    approve(run.run_dir, candidate=1, reviewer="alice")
    with pytest.raises(ApprovalError, match="already approved"):
        approve(run.run_dir, candidate=1, reviewer="mallory")
    core = repos / "pager" / "pager" / "core.py"
    core.write_text(core.read_text() + "\n# local edit\n")
    with pytest.raises(ApprovalError, match="repository changed"):
        apply_approved(run.run_dir, repos / "pager", allowed_roots=(repos,))


def test_apply_detects_a_tampered_candidate(approved_setup):
    run, repos = approved_setup
    approve(run.run_dir, candidate=1, reviewer="alice")
    patch = run.run_dir / "candidate-1.patch"
    patch.write_text(patch.read_text().replace("(page - 1)", "(page - 2)"))
    with pytest.raises(ApprovalError, match="changed after approval"):
        apply_approved(run.run_dir, repos / "pager", allowed_roots=(repos,))


def test_apply_respects_path_policy_and_protected_roots(approved_setup, tmp_path):
    run, repos = approved_setup
    approve(run.run_dir, candidate=1, reviewer="alice")
    with pytest.raises(PolicyError):
        apply_approved(run.run_dir, repos / "pager", allowed_roots=(tmp_path / "elsewhere",))
    with pytest.raises(PolicyError, match="protected"):
        apply_approved(
            run.run_dir, repos / "pager", allowed_roots=(repos,), protected_roots=(repos,)
        )


def test_risky_candidates_need_explicit_acknowledgement(sandbox, tmp_path):
    t = task(T07)
    risky = json.dumps(
        {
            "summary": "drop the check",
            "edits": [{"path": "filestore/paths.py", "old": T07_RAISE, "new": "        pass\n"}],
        }
    )
    run = repair(
        snapshot_of(T07),
        t.read_issue(),
        ScriptedBackend([risky]),
        sandbox,
        budget=RepairBudget(max_attempts=1),
        runs_dir=tmp_path,
        task_id=t.id,
    )
    card = run.selected
    assert any(f.rule == "removed-validation" for f in card.security)
    with pytest.raises(ApprovalError, match="acknowledge-risks"):
        approve(run.run_dir, candidate=1, reviewer="bob")
    record = approve(run.run_dir, candidate=1, reviewer="bob", acknowledge_risks=True)
    assert record.acknowledged_risks
    assert load_approval(run.run_dir).acknowledged_risks == record.acknowledged_risks


def test_cli_review_approve_apply(sandbox, tmp_path, monkeypatch, capsys):
    repos = tmp_path / "repos"
    shutil.copytree(task("t01_paginate_off_by_one").repo_dir, repos / "pager")
    issue = tmp_path / "issue.md"
    issue.write_text(task("t01_paginate_off_by_one").read_issue())
    script = tmp_path / "script.json"
    script.write_text(json.dumps([task("t01_paginate_off_by_one").solution_path.read_text()]))
    monkeypatch.setenv("CODEREPAIR_ALLOWED_ROOTS", str(repos))
    monkeypatch.setenv("CODEREPAIR_SANDBOX", sandbox.name)
    args = ["repair", "--repo", str(repos / "pager"), "--issue", str(issue)]
    assert main([*args, "--backend", "scripted", "--script", str(script), "--no-color"]) == 0
    runs_dir = tmp_path / "runs"
    run_id = next(runs_dir.iterdir()).name
    capsys.readouterr()
    assert main(["review", run_id, "--no-color"]) == 0
    assert "#1 candidate 1" in capsys.readouterr().out
    assert main(["approve", run_id, "--reviewer", "carol"]) == 0
    assert main(["apply", run_id, "--repo", str(repos / "pager")]) == 0
    assert "No commit, push or merge" in capsys.readouterr().out
    assert main(["approve", "../../etc", "--reviewer", "x"]) == 2


def test_fixture_tasks_are_protected_from_apply(approved_setup, monkeypatch, capsys):
    run, _ = approved_setup
    approve(run.run_dir, candidate=1, reviewer="alice")
    monkeypatch.setenv("CODEREPAIR_RUNS_DIR", str(run.run_dir.parent))
    monkeypatch.setenv("CODEREPAIR_ALLOWED_ROOTS", str(TASKS_DIR))
    code = main(["apply", run.run_id, "--repo", str(task("t01_paginate_off_by_one").repo_dir)])
    assert code == 2 and "protected" in capsys.readouterr().err
