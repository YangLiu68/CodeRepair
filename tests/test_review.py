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


# ------------------------------------------------- regressions from the M4-M7 review


def test_type_check_cannot_be_hijacked_by_a_repository_module(tmp_path):
    """A repo with its own mypy.py / typing_extensions.py must not run on the host."""
    marker = tmp_path / "hijacked"
    payload = f"import pathlib\npathlib.Path({str(marker)!r}).write_text('x')\n"
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("def f():\n    return 1\n")
    for name in ("mypy.py", "typing_extensions.py", "sitecustomize.py"):
        (repo / name).write_text(payload)
    snapshot = ingest_repository(repo, (tmp_path,))
    result = typecheck_delta(snapshot, {"pkg/__init__.py": "def f():\n    return 2\n"})
    # mypy may refuse to analyse a tree that shadows library modules ("error" is never a
    # pass); what matters is that the planted modules did not execute.
    assert result.status in ("ok", "skipped", "error")
    assert not marker.exists()


def test_hidden_characters_are_flagged_and_never_printed_raw(capsys):
    from coderepair.cli import colorize_diff
    from coderepair.security import display_safe

    snapshot = snapshot_of(T07)
    sneaky = T07_RAISE + "        # \x1b[1A\x1b[2K harmless\n        x = '‮'\n"
    rules = {f.rule for f in security_review(snapshot, _t07_with(sneaky))}
    assert "hidden-characters" in rules
    shown = colorize_diff("+# \x1b[1A\x1b[2K\n+x = '‮'\n", color=False)
    assert "\x1b" not in shown and "‮" not in shown
    assert "\\u001b" in shown and "\\u202e" in shown
    assert display_safe("tab\tand newline\n") == "tab\tand newline\n"


def test_writes_never_follow_symlinked_directories(tmp_path):
    """If tests/ (or any parent) is a symlink, nothing is written through it."""
    import os

    from coderepair.approval import _check_target, _write_target

    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "tests").symlink_to(outside, target_is_directory=True)
    (root / "pkg").mkdir()
    (root / "pkg" / "mod.py").write_text("x = 1\n")
    (root / "pkg" / "link.py").symlink_to(outside / "target.py")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(ApprovalError, match="refusing to write through"):
            _check_target(fd, "tests/test_new.py", None)
        with pytest.raises(ApprovalError, match="refusing to write through"):
            _write_target(fd, "tests/test_new.py", "x")
        with pytest.raises(ApprovalError, match="not a regular file"):
            _check_target(fd, "pkg/link.py", "")
        with pytest.raises(ApprovalError, match="changed since the run"):
            _check_target(fd, "pkg/mod.py", "x = 2\n")
        _check_target(fd, "pkg/mod.py", "x = 1\n")
        _write_target(fd, "pkg/mod.py", "x = 3\n")
    finally:
        os.close(fd)
    assert list(outside.iterdir()) == []
    assert (root / "pkg" / "mod.py").read_text() == "x = 3\n"


def test_apply_is_bound_to_the_approved_repository_and_reproduction_test(approved_setup, tmp_path):
    run, repos = approved_setup
    twin = repos / "pager-copy"
    shutil.copytree(repos / "pager", twin)
    approve(run.run_dir, candidate=1, reviewer="alice")
    with pytest.raises(ApprovalError, match="this approval is for"):
        apply_approved(run.run_dir, twin, allowed_roots=(repos,))


def test_reproduction_test_cannot_be_swapped_after_approval(sandbox, tmp_path):
    repos = tmp_path / "repos"
    shutil.copytree(task("t02_mutable_default_tags").repo_dir, repos / "notes")
    t = task("t02_mutable_default_tags")
    run = repair(
        ingest_repository(repos / "notes", (repos,)),
        t.read_issue(),
        ScriptedBackend([T02_GOLD, T02_REPRO]),
        sandbox,
        budget=RepairBudget(repro_test=True),
        runs_dir=tmp_path / "runs",
    )
    approve(run.run_dir, candidate=None, reviewer="alice", include_reproduction_test=True)
    summary_path = run.run_dir / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary["reproduction_test"]["code"] += "\nimport os\n"
    summary_path.write_text(json.dumps(summary))
    with pytest.raises(ApprovalError, match="reproduction test changed"):
        apply_approved(run.run_dir, repos / "notes", allowed_roots=(repos,))


def test_protected_roots_are_compared_by_inode(tmp_path):
    from coderepair.security import same_or_inside

    protected = tmp_path / "bench" / "tasks"
    (protected / "t01" / "repo").mkdir(parents=True)
    variant = tmp_path / "bench" / "TASKS" / "t01" / "repo"
    if not variant.exists():
        pytest.skip("case-sensitive file system")
    assert same_or_inside(variant, protected)
    assert not same_or_inside(tmp_path, protected)


def test_no_extra_model_calls_unless_more_candidates_are_requested(sandbox):
    wrong = json.dumps(
        {
            "summary": "x",
            "edits": [
                {
                    "path": "pager/core.py",
                    "old": "    start = page * per_page\n",
                    "new": "    start = page + 0 * per_page\n",
                }
            ],
        }
    )
    t = task("t01_paginate_off_by_one")
    backend = ScriptedBackend([wrong, wrong, wrong])
    run = repair(
        snapshot_of(t.id),
        t.read_issue(),
        backend,
        sandbox,
        budget=RepairBudget(max_attempts=2),
        task_id=t.id,
    )
    assert run.samples == [] and len(backend.requests) == 2


def test_passing_candidates_survive_the_scoring_cap(sandbox, monkeypatch):
    import coderepair.loop as loop

    monkeypatch.setattr(loop, "MAX_SCORED_CANDIDATES", 1)
    t = task("t01_paginate_off_by_one")
    wrong = json.dumps(
        {
            "summary": "x",
            "edits": [
                {
                    "path": "pager/core.py",
                    "old": "    start = page * per_page\n",
                    "new": "    start = page + 0 * per_page\n",
                }
            ],
        }
    )
    gold = t.solution_path.read_text()
    run = repair(snapshot_of(t.id), t.read_issue(), ScriptedBackend([wrong, gold]), sandbox)
    assert run.status == LOOP_FIXED and "(page - 1)" in run.diff


def test_skipped_baseline_tests_are_not_failures():
    from coderepair.agent import AttemptResult
    from coderepair.candidates import Candidate, score_candidates
    from coderepair.patch import apply_proposal
    from coderepair.sandbox.base import SandboxResult
    from coderepair.sandbox.results import TestResults
    from coderepair.trace import Trace

    snapshot = snapshot_of("t01_paginate_off_by_one")
    patch = apply_proposal(snapshot, task("t01_paginate_off_by_one").load_solution())
    baseline = SandboxResult(
        "x", "x", 1, 0.1, results=TestResults({"a": "failed", "b": "skipped", "c": "passed"}, (), 1)
    )
    visible = SandboxResult(
        "x", "x", 0, 0.1, results=TestResults({"a": "passed", "b": "skipped", "c": "passed"}, (), 0)
    )
    candidate = Candidate(1, "x", AttemptResult("proposed", patch=patch), visible)
    (card,) = score_candidates([candidate], snapshot, baseline, None, None, Trace("x"))
    assert card.fixes == ["a"] and card.regressions == [] and card.visible_all_pass


def test_sandbox_failure_while_scoring_affects_only_that_candidate(monkeypatch):
    import coderepair.candidates as candidates_mod
    from coderepair.agent import AttemptResult
    from coderepair.candidates import Candidate, score_candidates
    from coderepair.patch import apply_proposal
    from coderepair.sandbox.base import SandboxError
    from coderepair.trace import Trace

    def broken(*args, **kwargs):
        raise SandboxError("sandbox-exec missing")

    monkeypatch.setattr(candidates_mod, "run_repo_tests", broken)
    snapshot = snapshot_of("t01_paginate_off_by_one")
    patch = apply_proposal(snapshot, task("t01_paginate_off_by_one").load_solution())
    candidate = Candidate(1, "x", AttemptResult("proposed", patch=patch))
    (card,) = score_candidates([candidate], snapshot, None, None, None, Trace("x"))
    assert not card.visible_all_pass and "visible tests not run" in card.problems[0]


def test_deeply_nested_model_output_is_rejected_not_crashing():
    from coderepair.patch import ProposalParseError, parse_proposal

    with pytest.raises(ProposalParseError):
        parse_proposal("[" * 50_000)
