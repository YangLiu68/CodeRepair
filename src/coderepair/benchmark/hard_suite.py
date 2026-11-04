"""Build the hard tier: one shared repository, one seeded bug per task.

Source layout (``benchmarks/hard_src/``)::

    base/                   the clean repository; all of its own tests pass
    tasks/<id>/
        task.toml           category, difficulty, issue_style, summary, seeded_bug, fail_to_pass
        issue.md            the agent-visible issue
        bug.json            [{"path", "old", "new"}]: edits that seed the bug into base/
        test_hidden_*.py    held-out tests

Each built task (``benchmarks/hard/<id>/``) has the standard layout described in
``tasks.py``. Its repository is ``base/`` with the bug seeded, and its gold solution is the
exact inverse of ``bug.json``. ``pass_to_pass`` is not written by hand: the builder runs the
buggy repository's visible and hidden tests (first-party code, host runner on a temporary
copy) and refuses to write a task whose failing tests differ from the declared
``fail_to_pass``. ``validate-fixtures --suite hard`` then checks every task independently.
"""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

from .tasks import TASK_ID_RE, TaskError, _load
from .validate import HostFixtureRunner

_IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".DS_Store")
_REQUIRED = ("category", "difficulty", "issue_style", "summary", "seeded_bug", "fail_to_pass")


def load_bug(path: Path) -> list[dict[str, str]]:
    edits = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(edits, list) or not edits:
        raise TaskError(f"{path}: expected a non-empty list of edits")
    for edit in edits:
        if set(edit) != {"path", "old", "new"} or edit["old"] == edit["new"]:
            raise TaskError(f"{path}: every edit needs distinct 'path', 'old' and 'new'")
    return edits


def seed_bug(base: Path, repo: Path, edits: list[dict[str, str]]) -> None:
    """Copy ``base`` to ``repo`` and apply ``edits``; each ``old`` must occur exactly once."""
    shutil.copytree(base, repo, ignore=_IGNORE)
    for edit in edits:
        target = repo / edit["path"]
        text = target.read_text(encoding="utf-8")
        count = text.count(edit["old"])
        if count != 1:
            raise TaskError(f"{edit['path']}: seeding anchor found {count} times (need 1)")
        target.write_text(text.replace(edit["old"], edit["new"]), encoding="utf-8")


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_list(values: list[str]) -> str:
    if not values:
        return "[]"
    return "[\n" + "".join(f"    {_toml_string(v)},\n" for v in values) + "]"


def render_task_toml(task_id: str, meta: dict, pass_to_pass: list[str]) -> str:
    lines = [f"id = {_toml_string(task_id)}"]
    for key in ("category", "difficulty", "issue_style"):
        lines.append(f"{key} = {_toml_string(meta[key])}")
    lines.append(f"fail_to_pass = {_toml_list(list(meta['fail_to_pass']))}")
    lines.append(f"pass_to_pass = {_toml_list(sorted(pass_to_pass))}")
    lines += [
        "",
        "[provenance]",
        f"origin = {_toml_string('original work written for CodeRepair (hard tier)')}",
        f"base = {_toml_string('benchmarks/hard_src/base')}",
        f"seeded_bug = {_toml_string(meta['seeded_bug'])}",
    ]
    return "\n".join(lines) + "\n"


def build_task(source: Path, base: Path, dest_root: Path, *, timeout_s: int = 120) -> Path:
    """Build one task from ``source`` into ``dest_root/<id>``; returns the task directory."""
    task_id = source.name
    if not TASK_ID_RE.match(task_id) or not task_id.startswith("h"):
        raise TaskError(f"hard-tier task ids look like h01_name, got {task_id!r}")
    meta = tomllib.loads((source / "task.toml").read_text(encoding="utf-8"))
    missing = [k for k in _REQUIRED if k not in meta]
    if missing:
        raise TaskError(f"{task_id}: task.toml is missing {missing}")
    edits = load_bug(source / "bug.json")
    hidden = sorted(source.glob("test_hidden_*.py"))
    if not hidden:
        raise TaskError(f"{task_id}: no test_hidden_*.py files")

    dest = dest_root / task_id
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    seed_bug(base, dest / "repo", edits)
    shutil.copy2(source / "issue.md", dest / "issue.md")
    (dest / "hidden_tests").mkdir()
    for path in hidden:
        shutil.copy2(path, dest / "hidden_tests" / path.name)
    gold = {
        "summary": meta["summary"],
        "edits": [{"path": e["path"], "old": e["new"], "new": e["old"]} for e in edits],
    }
    (dest / "solution.json").write_text(json.dumps(gold, indent=2) + "\n", encoding="utf-8")

    # Provisional task.toml so the task loads, then measure the buggy outcomes.
    (dest / "task.toml").write_text(render_task_toml(task_id, meta, []), encoding="utf-8")
    run = HostFixtureRunner(timeout_s)(_load(dest), "buggy_all", gold=False, hidden=True)
    if run.collect_errors:
        raise TaskError(f"{task_id}: collection errors {run.collect_errors}\n{run.output_tail}")
    failed = {t for t, outcome in run.outcomes.items() if outcome != "passed"}
    declared = set(meta["fail_to_pass"])
    if failed != declared:
        raise TaskError(
            f"{task_id}: failing tests differ from fail_to_pass: "
            f"unexpected {sorted(failed - declared)}, not failing {sorted(declared - failed)}"
        )
    passing = [t for t, outcome in run.outcomes.items() if outcome == "passed"]
    (dest / "task.toml").write_text(render_task_toml(task_id, meta, passing), encoding="utf-8")
    return dest


def build_suite(source_root: Path, dest_root: Path, *, timeout_s: int = 120) -> list[Path]:
    base = source_root / "base"
    sources = sorted(
        p for p in (source_root / "tasks").iterdir() if p.is_dir() and TASK_ID_RE.match(p.name)
    )
    dest_root.mkdir(parents=True, exist_ok=True)
    stale = [
        p
        for p in dest_root.iterdir()
        if p.is_dir() and TASK_ID_RE.match(p.name) and p.name not in {s.name for s in sources}
    ]
    for path in stale:
        shutil.rmtree(path)
    return [build_task(s, base, dest_root, timeout_s=timeout_s) for s in sources]


def check_built(source_root: Path, dest_root: Path) -> list[str]:
    """Differences between the built tasks and what their sources would build (no test runs)."""
    problems = []
    base = source_root / "base"
    sources = {
        p.name: p
        for p in (source_root / "tasks").iterdir()
        if p.is_dir() and TASK_ID_RE.match(p.name)
    }
    built = {p.name for p in dest_root.iterdir() if p.is_dir() and TASK_ID_RE.match(p.name)}
    for name in sorted(built ^ set(sources)):
        problems.append(f"{name}: built and source task sets differ")
    for name in sorted(built & set(sources)):
        source, dest = sources[name], dest_root / name
        expected: dict[str, str] = {}
        for path in sorted(base.rglob("*")):
            rel = path.relative_to(base)
            if path.is_file() and not set(rel.parts) & {"__pycache__", ".pytest_cache"}:
                expected[rel.as_posix()] = path.read_text(encoding="utf-8")
        for edit in load_bug(source / "bug.json"):
            expected[edit["path"]] = expected[edit["path"]].replace(edit["old"], edit["new"], 1)
        actual = {
            p.relative_to(dest / "repo").as_posix(): p.read_text(encoding="utf-8")
            for p in (dest / "repo").rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        }
        if expected != actual:
            keys = expected.keys() | actual.keys()
            changed = sorted(k for k in keys if expected.get(k) != actual.get(k))
            problems.append(f"{name}: repo differs from base + bug.json in {changed}")
        if (source / "issue.md").read_text() != (dest / "issue.md").read_text():
            problems.append(f"{name}: issue.md is stale")
        for path in source.glob("test_hidden_*.py"):
            built_test = dest / "hidden_tests" / path.name
            if not built_test.exists() or built_test.read_text() != path.read_text():
                problems.append(f"{name}: hidden test {path.name} is stale")
        meta = tomllib.loads((source / "task.toml").read_text(encoding="utf-8"))
        built_meta = tomllib.loads((dest / "task.toml").read_text(encoding="utf-8"))
        for key in ("category", "difficulty", "issue_style", "fail_to_pass"):
            if meta[key] != built_meta.get(key):
                problems.append(f"{name}: task.toml {key} is stale")
    return problems
