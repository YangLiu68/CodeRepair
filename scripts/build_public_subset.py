"""Build the Milestone 6 public task suite from a QuixBugs checkout.

QuixBugs (https://github.com/jkoppel/QuixBugs, MIT License) pairs 40 small
programs, each with a one-line bug, with corrected versions and JSON test
cases. This script turns a deterministic subset of the Python programs into
CodeRepair tasks under ``benchmarks/public/``:

* ``repo/`` holds the buggy program verbatim (code + its specification
  docstring), a visible test file with a few cases and a ``conftest.py`` that
  gives every test a 2-second time limit, so bugs that loop forever fail fast.
* ``hidden_tests/`` holds the remaining cases, ``solution.json`` the minimal
  edits that turn the buggy code into the upstream correction, and ``issue.md``
  a bug report generated only from test inputs, the expected outputs and what
  the buggy program actually returned.

Leakage controls: the corrected program, the upstream test files and any
QuixBugs naming are never placed in ``repo/`` or the issue; the issue quotes
only a failing case that is not among the hidden tests; outputs observed from
running code are produced in the sandbox; the checkout is read as text and never
imported on the host. Selection rule: every program (or the first ``--count``
in alphabetical order) that is self-contained (no graph/node helpers), whose
upstream correction passes every case, whose bug fails at least two cases, and
whose outcomes are identical in two runs. The rule never looks at model results.

Usage:
    uv run python scripts/build_public_subset.py --source /path/to/QuixBugs --commit <sha>
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path

from coderepair.benchmark.manifest import write_manifest, write_solution_patch
from coderepair.benchmark.tasks import list_tasks
from coderepair.config import PROJECT_ROOT
from coderepair.patch import Edit, PatchProposal, apply_proposal
from coderepair.repo import ingest_repository
from coderepair.sandbox.base import SandboxJob, SandboxLimits
from coderepair.sandbox.factory import make_sandbox
from coderepair.sandbox.workspace import prepare_run_dir

OUT = PROJECT_ROOT / "benchmarks" / "public"
NEEDS_HELPERS = {
    "breadth_first_search",
    "depth_first_search",
    "detect_cycle",
    "minimum_spanning_tree",
    "reverse_linked_list",
    "shortest_path_length",
    "shortest_path_lengths",
    "shortest_paths",
    "topological_ordering",
    "node",
}
APPROX = {"sqrt"}  # compared with pytest.approx(abs=epsilon), as upstream does
#: Programs whose specification allows more than one correct output. Their tests check
#: the specified property instead of the one output the upstream correction happens to give.
SPEC_CHECKS = {
    # "If multiple subsequences of equal length exist, either is OK."
    "longest_common_subsequence": (
        """def _is_subsequence(small, big):
    rest = iter(big)
    return all(ch in rest for ch in small)
""",
        "assert isinstance(result, str) and len(result) == len(expected)\n"
        "    assert _is_subsequence(result, args[0]) and _is_subsequence(result, args[1])",
    ),
    # "A list of lists, each representing a different subset": no order is specified.
    "powerset": (
        """def _subsets(value):
    return sorted(sorted(repr(v) for v in subset) for subset in value)
""",
        "assert _subsets(result) == _subsets(expected)",
    ),
    # "A list of all length-k ascending sequences": each sequence is ordered, the list is not.
    "subsequences": ("", "assert sorted(_normalize(result)) == sorted(_normalize(expected))"),
}
GOLD_MAX_SECONDS = 0.5  # the correction must run every case well inside the 2-second limit
MAX_HIDDEN_PASSING = 4
MAX_HIDDEN_FAILING = 6

CONFTEST = '''\
import signal

import pytest


def _expired(signum, frame):
    raise TimeoutError("test exceeded its 2 second time limit")


@pytest.hookimpl(hookwrapper=True)
def pytest_pyfunc_call(pyfuncitem):
    """Fail (instead of hang) when a test function does not return within 2 seconds.

    The timer covers only the test function itself: it is disarmed before pytest's
    own teardown and reporting, so a long traceback is never interrupted mid-report.
    """
    previous = signal.signal(signal.SIGALRM, _expired)
    signal.setitimer(signal.ITIMER_REAL, 2.0)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
'''

PYPROJECT = """\
[project]
name = "algo"
version = "0.1.0"
requires-python = ">=3.9"

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
"""

NORMALIZE = '''\
def _normalize(value):
    """Compare results structurally: tuples as lists, iterators materialised."""
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if hasattr(value, "__next__"):
        return [_normalize(v) for v in value]
    return value
'''

OBSERVE = """\
import json
import os
import re
import time

import pytest

from algo.{name} import {name}

CASES = {cases!r}


@pytest.mark.parametrize("index", range(len(CASES)))
def test_observe(index):
    args, _expected = CASES[index]
    started = time.perf_counter()
    try:
        value = {name}(*args)
        if hasattr(value, "__next__"):
            value = list(value)
        # Object addresses differ between runs; keep the issue text reproducible.
        text = re.sub(r" at 0x[0-9a-fA-F]+", " at 0x...", repr(value))
        if len(text) > 300:  # keep both ends: the difference is often at the end
            text = text[:150] + " ... " + text[-150:]
            record = {{"case": index, "repr": text, "shortened": True}}
        else:
            record = {{"case": index, "repr": text}}
    except BaseException as exc:  # noqa: BLE001 - recording what the buggy code does
        record = {{"case": index, "error": type(exc).__name__}}
    record["seconds"] = round(time.perf_counter() - started, 3)
    with open(os.path.join(os.environ["TMPDIR"], "observed.jsonl"), "a") as fh:
        fh.write(json.dumps(record) + "\\n")
"""


def test_module(name: str, cases: list[tuple[int, list]], *, hidden: bool) -> str:
    func = f"test_hidden_{name}" if hidden else f"test_{name}"
    helper, check = SPEC_CHECKS.get(name, ("", ""))
    compare = check or (
        "assert result == pytest.approx(expected, abs=args[-1])"
        if name in APPROX
        else "assert _normalize(result) == _normalize(expected)"
    )
    params = ",\n".join(
        f"    pytest.param({args!r}, {expected!r}, id='case{index}')"
        for index, (args, expected) in cases
    )
    return (
        "import pytest\n\n"
        f"from algo.{name} import {name}\n\n\n"
        + (NORMALIZE + "\n\n" if name not in APPROX else "")
        + (helper + "\n\n" if helper else "")
        + "@pytest.mark.parametrize(\n"
        + '    "args, expected",\n'
        + "    [\n"
        + textwrap.indent(params, "    ")
        + ",\n    ],\n)\n"
        + f"def {func}(args, expected):\n"
        + f"    result = {name}(*args)\n"
        + f"    {compare}\n"
    )


def code_part(text: str) -> str:
    """The program without the trailing specification/alternatives string."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.rstrip() == '"""':
            lines = lines[:i]
            break
    return "".join(lines).strip("\n") + "\n"


def gold_edits(buggy_text: str, correct_text: str) -> PatchProposal:
    """Minimal search/replace edits that turn the buggy code into the corrected code."""
    old_lines = code_part(buggy_text).splitlines(keepends=True)
    new_lines = code_part(correct_text).splitlines(keepends=True)
    edits = []
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        context = 0
        while True:
            lo, hi = max(0, i1 - context), min(len(old_lines), i2 + context)
            old = "".join(old_lines[lo:hi])
            if old and buggy_text.count(old) == 1:
                break
            context += 1
            if context > len(old_lines):
                raise ValueError("cannot build a unique anchor")
        new = "".join(old_lines[lo:i1]) + "".join(new_lines[j1:j2]) + "".join(old_lines[i2:hi])
        edits.append(Edit(path="", old=old, new=new))
    return PatchProposal(summary="", edits=edits)


class SessionIncomplete(RuntimeError):
    pass


def run_cases(sandbox, repo_files: dict[str, str], name: str, cases, overlay=None):
    """Run every case in the sandbox; return (outcomes per case index, observed values)."""
    with tempfile.TemporaryDirectory(prefix="coderepair-public-") as tmp:
        root = Path(tmp) / "repo"
        for rel, text in repo_files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        observe = OBSERVE.format(name=name, cases=[c for _, c in cases])
        (root / "tests" / "test_observe.py").write_text(observe, encoding="utf-8")
        (root / "tests" / f"test_{name}.py").write_text(
            test_module(name, cases, hidden=False), encoding="utf-8"
        )
        snapshot = ingest_repository(root, (Path(tmp),))
        run_dir = prepare_run_dir(snapshot, overlay=overlay)
        try:
            result = sandbox.run(
                SandboxJob(run_dir.workspace, limits=SandboxLimits(wall_timeout_s=120))
            )
            observed = {}
            obs = run_dir.tmp / "observed.jsonl"
            if obs.is_file() and not obs.is_symlink():
                for line in obs.read_text(encoding="utf-8", errors="replace").splitlines()[:500]:
                    record = json.loads(line)
                    observed[int(record["case"])] = record
        finally:
            run_dir.cleanup()
    if not result.completed:
        reason = result.limit_exceeded or "; ".join(result.problems) or "no results"
        raise SessionIncomplete(f"test session did not complete ({reason})")
    missing = [
        i
        for i, _ in cases
        if f"tests/test_{name}.py::test_{name}[case{i}]" not in result.results.outcomes
    ]
    if missing:
        raise SessionIncomplete(f"no outcome for case(s) {missing}")
    outcomes = {}
    for index, _ in cases:
        outcomes[index] = result.results.outcomes.get(
            f"tests/test_{name}.py::test_{name}[case{index}]"
        )
    return outcomes, observed


def _untimed(observed: dict) -> dict:
    return {i: {k: v for k, v in r.items() if k != "seconds"} for i, r in observed.items()}


def issue_text(name: str, reported: list[tuple[int, list]], observed: dict, visible_failing):
    """Bug report built only from the reported example, which is never a hidden test."""
    lines = [f"# `{name}` returns wrong results for some inputs", ""]
    lines.append(
        f"`{name}` in `algo/{name}.py` does not do what its docstring specifies for every input."
    )
    lines.append("")
    for index, (args, expected) in reported:
        call = f"{name}({', '.join(json.dumps(a) for a in args)})"
        record = observed.get(index, {})
        if record.get("error") == "TimeoutError":
            got = "does not return (it runs for more than 2 seconds)"
        elif "error" in record:
            got = f"raises `{record['error']}`"
        elif record.get("shortened"):
            got = f"returns `{record['repr']}` (shortened; the middle is omitted)"
        else:
            got = f"returns `{record['repr']}`"
        lines.append(f"- `{call}` {got}; expected `{json.dumps(expected)}`.")
    if visible_failing is not None:
        lines += ["", f"The failing test `{visible_failing}` reproduces it."]
    lines += ["", "algo 0.1.0, Python 3.12"]
    return "\n".join(lines) + "\n"


def build(source: Path, commit: str, count: int, sandbox_name: str) -> int:
    sandbox = make_sandbox(sandbox_name, PROJECT_ROOT / ".cache")
    programs = sorted(p.stem for p in (source / "python_programs").glob("*.py"))
    programs = [p for p in programs if p not in NEEDS_HELPERS and not p.endswith("_test")]
    if OUT.exists():
        for child in OUT.iterdir():
            if child.is_dir() and child.name[:1] == "q":
                shutil.rmtree(child)
    OUT.mkdir(parents=True, exist_ok=True)
    built = 0
    report = []
    for name in programs:
        if built >= count:
            break
        buggy = (source / "python_programs" / f"{name}.py").read_text(encoding="utf-8")
        correct = (source / "correct_python_programs" / f"{name}.py").read_text(encoding="utf-8")
        cases = [
            (i, json.loads(line))
            for i, line in enumerate(
                (source / "json_testcases" / f"{name}.json").read_text().splitlines()
            )
            if line.strip()
        ]
        try:
            proposal = gold_edits(buggy, correct)
        except ValueError as exc:
            report.append(f"skip {name}: {exc}")
            continue
        algo_path = f"algo/{name}.py"
        proposal = PatchProposal(
            summary=f"Upstream correction of {name}.",
            edits=[Edit(path=algo_path, old=e.old, new=e.new) for e in proposal.edits],
        )
        repo_files = {
            "pyproject.toml": PYPROJECT,
            "algo/__init__.py": "",
            algo_path: buggy,
            "tests/conftest.py": CONFTEST,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            for rel, text in repo_files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text, encoding="utf-8")
            snapshot = ingest_repository(root, (Path(tmp),))
            gold = apply_proposal(snapshot, proposal)
        if not gold.ok or code_part(gold.changed_files[algo_path]) != code_part(correct):
            report.append(f"skip {name}: gold edits do not reproduce the correction")
            continue
        try:
            buggy_outcomes, observed = run_cases(sandbox, repo_files, name, cases)
            gold_outcomes, gold_observed = run_cases(
                sandbox, repo_files, name, cases, overlay=gold.changed_files
            )
            # Outcomes must not depend on timing or load: a second run has to agree.
            again, observed_again = run_cases(sandbox, repo_files, name, cases)
        except SessionIncomplete as exc:
            report.append(f"skip {name}: {exc}")
            continue
        if again != buggy_outcomes or _untimed(observed_again) != _untimed(observed):
            report.append(f"skip {name}: outcomes differ between two runs of the buggy code")
            continue
        slow = [i for i, r in gold_observed.items() if r.get("seconds", 0) > GOLD_MAX_SECONDS]
        if slow:
            report.append(
                f"skip {name}: the correction needs more than {GOLD_MAX_SECONDS}s on case(s) {slow}"
            )
            continue
        valid = [i for i, _ in cases if gold_outcomes.get(i) == "passed"]
        if len(valid) < len(cases):
            report.append(f"skip {name}: correction fails {len(cases) - len(valid)} case(s)")
            continue
        failing = [(i, c) for i, c in cases if buggy_outcomes.get(i) == "failed"]
        passing = [(i, c) for i, c in cases if buggy_outcomes.get(i) == "passed"]
        if len(failing) < 2:
            # One failing case is needed for the issue (or the visible test) and at least
            # one other must stay hidden, so the issue never quotes a hidden test.
            report.append(f"skip {name}: the bug fails fewer than two test cases")
            continue
        if failing[0][0] not in observed:
            report.append(f"skip {name}: no observation for the reported case")
            continue
        built += 1
        task_id = f"q{built:02d}_{name}"
        visible = passing[:2]
        visible_failing_id = None
        reported = failing[:1]  # the example the issue describes; never hidden
        if built % 2 == 0 or not visible:
            visible = visible + reported
            visible_failing_id = f"tests/test_{name}.py::test_{name}[case{reported[0][0]}]"
        excluded = {i for i, _ in visible} | {i for i, _ in reported}
        hidden = [c for c in failing if c[0] not in excluded][:MAX_HIDDEN_FAILING] + [
            c for c in passing if c[0] not in excluded
        ][:MAX_HIDDEN_PASSING]
        hidden.sort()
        task_dir = OUT / task_id
        repo = task_dir / "repo"
        for rel, text in repo_files.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(text, encoding="utf-8")
        (repo / "tests" / f"test_{name}.py").write_text(
            test_module(name, visible, hidden=False), encoding="utf-8"
        )
        (task_dir / "hidden_tests").mkdir(parents=True)
        (task_dir / "hidden_tests" / f"test_hidden_{name}.py").write_text(
            test_module(name, hidden, hidden=True), encoding="utf-8"
        )
        (task_dir / "issue.md").write_text(
            issue_text(name, reported, observed, visible_failing_id), encoding="utf-8"
        )
        (task_dir / "solution.json").write_text(
            proposal.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        failing_ids = {i for i, _ in failing}
        f2p = ([visible_failing_id] if visible_failing_id else []) + [
            f"tests/test_hidden_{name}.py::test_hidden_{name}[case{i}]"
            for i, _ in hidden
            if i in failing_ids
        ]
        p2p = sorted(
            [
                f"tests/test_{name}.py::test_{name}[case{i}]"
                for i, _ in visible
                if i not in failing_ids
            ]
            + [
                f"tests/test_hidden_{name}.py::test_hidden_{name}[case{i}]"
                for i, _ in hidden
                if i not in failing_ids
            ]
        )
        style = (
            "failing test provided; observed vs expected outputs"
            if visible_failing_id
            else "observed vs expected outputs only (issue-only)"
        )
        toml = [
            f'id = "{task_id}"',
            'category = "algorithm"',
            'difficulty = "easy"',
            f'issue_style = "{style}"',
            "fail_to_pass = [",
            *[f'    "{t}",' for t in f2p],
            "]",
            "pass_to_pass = [",
            *[f'    "{t}",' for t in p2p],
            "]",
            "",
            "[provenance]",
            'origin = "QuixBugs (Lin, Koppel, Chen, Solar-Lezama, SPLASH 2017 Companion)"',
            'source = "https://github.com/jkoppel/QuixBugs"',
            f'source_commit = "{commit}"',
            'license = "MIT (see benchmarks/public/LICENSE-QuixBugs.txt and LICENSE_NOTES.md)"',
            f'upstream_buggy = "python_programs/{name}.py"',
            f'upstream_fixed = "correct_python_programs/{name}.py"',
            f'upstream_cases = "json_testcases/{name}.json"',
            'created = "2026-10-15"',
            f'seeded_bug = "upstream QuixBugs defect in {name} (one-line bug)"',
        ]
        (task_dir / "task.toml").write_text("\n".join(toml) + "\n", encoding="utf-8")
        report.append(
            f"built {task_id}: {len(visible)} visible, {len(hidden)} hidden, "
            f"{len(f2p)} fail-to-pass"
        )
    shutil.copyfile(source / "LICENSE", OUT / "LICENSE-QuixBugs.txt")
    tasks = list_tasks(OUT)
    for task in tasks:
        write_solution_patch(task)
    write_manifest(tasks, OUT / "manifest.json")
    print("\n".join(report))
    print(f"{len(tasks)} public tasks in {OUT}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True, help="QuixBugs checkout")
    parser.add_argument("--commit", required=True, help="commit SHA of the checkout")
    parser.add_argument("--count", type=int, default=100, help="at most this many tasks")
    parser.add_argument("--sandbox", default="auto")
    args = parser.parse_args()
    if not (args.source / "LICENSE").is_file():
        print("error: --source does not look like a QuixBugs checkout", file=sys.stderr)
        return 2
    os.umask(0o022)
    return build(args.source.resolve(), args.commit, args.count, args.sandbox)


if __name__ == "__main__":
    sys.exit(main())
