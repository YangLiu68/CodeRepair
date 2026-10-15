from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from helpers import ALL_TASK_IDS, make_repo, snapshot_of, task

from coderepair.patch import (
    Edit,
    PatchPolicy,
    PatchProposal,
    ProposalParseError,
    apply_proposal,
    parse_proposal,
    path_violation,
    unified_diff,
)
from coderepair.repo import ingest_repository

PAGER = "t01_paginate_off_by_one"


def proposal(*edits: tuple[str, str, str], summary: str = "") -> PatchProposal:
    return PatchProposal(summary=summary, edits=[Edit(path=p, old=o, new=n) for p, o, n in edits])


# --------------------------------------------------------------------------- parse


def test_parse_plain_fenced_and_wrapped_json():
    body = {"summary": "s", "edits": [{"path": "a.py", "old": "x", "new": "y"}]}
    plain = json.dumps(body)
    assert parse_proposal(plain).edits[0].path == "a.py"
    assert parse_proposal(f"Here you go:\n```json\n{plain}\n```\n").summary == "s"
    assert parse_proposal(f"Sure! {plain} Hope that helps.").edits[0].new == "y"


def test_parse_ignores_extra_fields():
    raw = json.dumps(
        {
            "summary": "s",
            "confidence": 0.9,
            "edits": [{"path": "a", "old": "b", "new": "c", "why": "z"}],
        }
    )
    assert parse_proposal(raw).edits[0].old == "b"


@pytest.mark.parametrize("raw", ["", "not json at all", "[1, 2]", '{"edits": [{"path": 1}]}'])
def test_parse_rejects_malformed_output(raw):
    with pytest.raises(ProposalParseError):
        parse_proposal(raw)


# ---------------------------------------------------------------------- path policy


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("../pager/core.py", "traversal"),
        ("pager/../../x.py", "traversal"),
        ("/etc/passwd", "absolute"),
        ("C:/Windows/x.py", "absolute"),
        ("pager\\core.py", "backslash"),
        ("./pager/core.py", "not normalized"),
        ("pager//core.py", "not normalized"),
        ("tests/test_core.py", "tests may not be modified"),
        ("pyproject.toml", "packaging"),
        (".github/workflows/ci.yml", "CI"),
        ("scripts/deploy.sh", "script"),
        ("pager/new_module.py", "does not exist"),
        (".env", "sensitive"),
        ("", "empty"),
    ],
)
def test_path_policy_rejections(path, reason):
    violation = path_violation(path, snapshot_of(PAGER), PatchPolicy())
    assert violation is not None and reason in violation


def test_path_policy_allows_source_files_and_optionally_tests():
    snapshot = snapshot_of(PAGER)
    assert path_violation("pager/core.py", snapshot, PatchPolicy()) is None
    assert (
        path_violation("tests/test_core.py", snapshot, PatchPolicy(allow_test_edits=True)) is None
    )


# ----------------------------------------------------------------------- application


def test_exact_edit_applies_and_produces_diff():
    result = apply_proposal(
        snapshot_of(PAGER),
        proposal(
            (
                "pager/core.py",
                "    start = page * per_page\n",
                "    start = (page - 1) * per_page\n",
            )
        ),
    )
    assert result.ok, result.errors
    assert result.outcomes[0].match == "exact"
    assert "-    start = page * per_page" in result.diff
    assert "+    start = (page - 1) * per_page" in result.diff
    assert (result.lines_added, result.lines_removed) == (1, 1)


def test_ambiguous_anchor_is_rejected():
    result = apply_proposal(snapshot_of(PAGER), proposal(("pager/core.py", "return", "return  ")))
    assert not result.ok
    assert "ambiguous" in result.errors[0]


def test_missing_anchor_is_rejected():
    result = apply_proposal(snapshot_of(PAGER), proposal(("pager/core.py", "no such text", "x")))
    assert not result.ok and "not found" in result.errors[0]


def test_trailing_whitespace_differences_are_tolerated_when_unique():
    old = "    start = page * per_page   \n    end = start + per_page\n"
    new = "    start = (page - 1) * per_page\n    end = start + per_page\n"
    result = apply_proposal(snapshot_of(PAGER), proposal(("pager/core.py", old, new)))
    assert result.ok, result.errors
    assert result.outcomes[0].match == "ignoring-trailing-whitespace"
    assert result.lines_added == 1


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [("", "x", "must not be empty"), ("    start = page * per_page\n",) * 2 + ("identical",)],
)
def test_degenerate_edits_are_rejected(old, new, message):
    result = apply_proposal(snapshot_of(PAGER), proposal(("pager/core.py", old, new)))
    assert not result.ok and message in result.errors[0]


def test_edits_that_break_syntax_are_rejected():
    result = apply_proposal(
        snapshot_of(PAGER),
        proposal(
            ("pager/core.py", "    start = page * per_page\n", "    start = (page - 1 * per_page\n")
        ),
    )
    assert not result.ok
    assert "invalid Python" in result.errors[0]


def test_patch_is_all_or_nothing():
    result = apply_proposal(
        snapshot_of(PAGER),
        proposal(
            (
                "pager/core.py",
                "    start = page * per_page\n",
                "    start = (page - 1) * per_page\n",
            ),
            ("tests/test_core.py", "assert", "pass  #"),
        ),
    )
    assert not result.ok
    assert result.diff == "" and result.changed_files == {}
    assert result.outcomes[0].applied and not result.outcomes[1].applied


def test_sequential_edits_to_one_file():
    result = apply_proposal(
        snapshot_of(PAGER),
        proposal(
            (
                "pager/core.py",
                "    start = page * per_page\n",
                "    offset = (page - 1) * per_page\n",
            ),
            ("pager/core.py", "    end = start + per_page\n", "    end = offset + per_page\n"),
            ("pager/core.py", "items[start:end]", "items[offset:end]"),
        ),
    )
    assert result.ok, result.errors
    assert result.changed_files["pager/core.py"].count("offset") == 3


def test_size_limits():
    many = [("pager/core.py", "x", "y")] * 5
    assert (
        "too many edits"
        in apply_proposal(snapshot_of(PAGER), proposal(*many), PatchPolicy(max_edits=4)).errors[0]
    )
    big_new = "    start = (page - 1) * per_page\n" + "    pass\n" * 30
    result = apply_proposal(
        snapshot_of(PAGER),
        proposal(("pager/core.py", "    start = page * per_page\n", big_new)),
        PatchPolicy(max_changed_lines=10),
    )
    assert not result.ok and "limit 10" in result.errors[0]


def test_risky_added_code_is_flagged_but_regex_compile_is_not():
    risky = apply_proposal(
        snapshot_of(PAGER),
        proposal(
            (
                "pager/core.py",
                "    start = page * per_page\n",
                "    import os; os.system('id')\n    start = (page - 1) * per_page\n",
            )
        ),
    )
    assert risky.ok
    assert any("process-execution" in w for w in risky.warnings)
    benign = apply_proposal(
        snapshot_of(PAGER),
        proposal(
            (
                "pager/core.py",
                "    start = page * per_page\n",
                "    start = (page - 1) * per_page  # re.compile(x)\n",
            )
        ),
    )
    assert benign.ok and benign.warnings == []


# ------------------------------------------------------------------------------ diff


def test_diff_marks_missing_newline_at_eof(tmp_path):
    repo = make_repo(tmp_path / "r", {"m.py": "a = 1\nb = 2"})
    result = apply_proposal(
        ingest_repository(repo, (tmp_path,)), proposal(("m.py", "b = 2", "b = 3"))
    )
    assert result.ok
    assert result.diff.endswith("+b = 3\n\\ No newline at end of file\n")


def test_unified_diff_is_empty_for_identical_files():
    assert unified_diff({"a.py": "x\n"}, {"a.py": "x\n"}) == ""


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
@pytest.mark.parametrize("task_id", ALL_TASK_IDS)
def test_gold_diffs_apply_with_git(task_id, tmp_path):
    """Generated diffs must be consumable by standard tooling (git apply)."""
    spec = task(task_id)
    workdir = tmp_path / "repo"
    shutil.copytree(spec.repo_dir, workdir)
    patch_file = tmp_path / "gold.patch"
    patch_file.write_text(spec.solution_patch_path.read_text())
    env = {
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
        "HOME": str(tmp_path),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    proc = subprocess.run(
        ["git", "apply", "--check", "--verbose", str(patch_file)],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
