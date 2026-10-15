"""Command-line interface: ``coderepair <command>``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .agent import STATUS_PROPOSED, ProposalRun, propose_patch
from .backends import BACKEND_NAMES, make_backend
from .benchmark.manifest import check_manifest, write_manifest, write_solution_patch
from .benchmark.retrieval_eval import evaluate_retrieval
from .benchmark.tasks import TaskError, list_tasks, load_task
from .benchmark.validate import validate_task
from .config import PROJECT_ROOT, Settings
from .issue import parse_issue
from .llm.base import BackendError
from .repo import ingest_repository
from .retrieval import rank_files
from .search import RepoIndex
from .security import PolicyError

FIRST_PARTY_TASKS = PROJECT_ROOT / "benchmarks" / "tasks"
MANIFEST_PATH = PROJECT_ROOT / "benchmarks" / "manifest.json"

_RESET, _RED, _GREEN, _CYAN, _BOLD, _YELLOW = (
    "\033[0m",
    "\033[31m",
    "\033[32m",
    "\033[36m",
    "\033[1m",
    "\033[33m",
)


def _use_color(args: argparse.Namespace) -> bool:
    return (
        sys.stdout.isatty()
        and not getattr(args, "no_color", False)
        and "NO_COLOR" not in os.environ
    )


def colorize_diff(diff: str, color: bool) -> str:
    if not color:
        return diff
    out = []
    for line in diff.splitlines():
        if line.startswith(("diff --git", "---", "+++")):
            out.append(f"{_BOLD}{line}{_RESET}")
        elif line.startswith("@@"):
            out.append(f"{_CYAN}{line}{_RESET}")
        elif line.startswith("+"):
            out.append(f"{_GREEN}{line}{_RESET}")
        elif line.startswith("-"):
            out.append(f"{_RED}{line}{_RESET}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def _snapshot_for_task(settings: Settings, task_id: str):
    task = load_task(settings.tasks_dir, task_id)
    return task, ingest_repository(task.repo_dir, settings.allowed_roots, settings.limits)


# ----------------------------------------------------------------------- commands


def cmd_tasks(args: argparse.Namespace, settings: Settings) -> int:
    tasks = list_tasks(settings.tasks_dir)
    if args.json:
        print(json.dumps([t.summary() for t in tasks], indent=2))
        return 0
    for task in tasks:
        print(f"{task.id:<34} {task.category:<26} {task.difficulty:<7} {task.title}")
    return 0


def cmd_show(args: argparse.Namespace, settings: Settings) -> int:
    task, snapshot = _snapshot_for_task(settings, args.task)
    issue = parse_issue(task.read_issue())
    print(task.read_issue().rstrip())
    print("\n--- parsed issue ---")
    print(json.dumps({k: v for k, v in issue.to_dict().items() if k != "code_blocks"}, indent=2))
    print("\n--- repository snapshot (agent-visible) ---")
    print(f"root: {snapshot.root}\ncontent hash: {snapshot.content_hash}")
    for path in snapshot.paths():
        print(f"  {path}")
    for excluded in snapshot.excluded:
        print(f"  [excluded: {excluded.reason}] {excluded.path}")
    return 0


def cmd_search(args: argparse.Namespace, settings: Settings) -> int:
    _, snapshot = _snapshot_for_task(settings, args.task)
    index = RepoIndex(snapshot)
    if args.symbol:
        for symbol in index.find_symbol(args.query):
            print(f"{symbol.path}:{symbol.line}-{symbol.end_line}  {symbol.kind} {symbol.qualname}")
        return 0
    for match in index.grep(args.query, regex=args.regex, path_glob=args.glob):
        print(f"{match.path}:{match.line}: {match.text}")
    return 0


def cmd_retrieve(args: argparse.Namespace, settings: Settings) -> int:
    task, snapshot = _snapshot_for_task(settings, args.task)
    ranked = rank_files(snapshot, RepoIndex(snapshot), parse_issue(task.read_issue()))
    for item in [r for r in ranked if r.score > 0][: args.n]:
        kind = "test  " if item.is_test else "source"
        print(f"{item.score:6.3f}  {kind}  {item.path}")
        for reason in item.reasons:
            print(f"                 - {reason}")
    return 0


def _print_run(run: ProposalRun, color: bool) -> None:
    banner_color = _YELLOW if color else ""
    reset = _RESET if color else ""
    if run.backend == "oracle":
        print(
            f"{banner_color}NOTE: the 'oracle' backend replays the task's gold solution. "
            "It checks the "
            f"pipeline end to end; it is NOT a repair result.{reset}\n"
        )
    elif run.is_mock:
        print(f"{banner_color}NOTE: '{run.backend}' is a mock backend (canned responses).{reset}\n")
    print(f"run:      {run.run_id}")
    print(f"backend:  {run.backend} ({run.model})")
    print(f"status:   {run.status}")
    print(f"context:  {', '.join(f.path for f in run.prompt.files)}")
    if run.proposal and run.proposal.summary:
        print(f"summary:  {run.proposal.summary}")
    for warning in run.warnings:
        print(f"{banner_color}warning:{reset}  {warning}")
    for error in run.errors:
        print(f"error:    {error}")
    if run.diff:
        print()
        print(colorize_diff(run.diff, color), end="")
        print(
            f"\n{run.patch.lines_added} line(s) added, {run.patch.lines_removed} removed. "
            "Nothing was written to the repository; review the diff above."
        )
    if run.run_dir:
        print(f"artifacts: {run.run_dir}")


def cmd_propose(args: argparse.Namespace, settings: Settings) -> int:
    backend_name = args.backend or settings.backend
    task = None
    if args.task:
        task = load_task(settings.tasks_dir, args.task)
        snapshot = ingest_repository(task.repo_dir, settings.allowed_roots, settings.limits)
        issue_text = task.read_issue()
    else:
        if not (args.repo and args.issue):
            print("error: give a TASK id, or both --repo and --issue", file=sys.stderr)
            return 2
        snapshot = ingest_repository(args.repo, settings.allowed_roots, settings.limits)
        issue_text = Path(args.issue).read_text(encoding="utf-8")
    backend = make_backend(backend_name, settings, task=task, script_path=args.script)
    run = propose_patch(
        snapshot,
        issue_text,
        backend,
        limits=settings.limits,
        runs_dir=None if args.no_save else settings.runs_dir,
        task_id=task.id if task else None,
    )
    if args.json:
        print(json.dumps({**run.summary_dict(), "diff": run.diff}, indent=2))
    else:
        _print_run(run, _use_color(args))
    return 0 if run.status == STATUS_PROPOSED else 1


def cmd_validate_fixtures(args: argparse.Namespace, settings: Settings) -> int:
    tasks = list_tasks(FIRST_PARTY_TASKS)
    if args.tasks:
        tasks = [t for t in tasks if t.id in set(args.tasks)]
    failures = 0
    results = []
    for task in tasks:
        report = validate_task(
            task, trusted_root=FIRST_PARTY_TASKS, timeout_s=settings.fixture_test_timeout_s
        )
        failures += not report.ok
        results.append(
            {"task_id": task.id, "ok": report.ok, "problems": report.problems, **report.counts}
        )
        if not args.json:
            status = "PASS" if report.ok else "FAIL"
            counts = ", ".join(f"{k}={v}" for k, v in report.counts.items())
            print(f"{status}  {task.id:<34} {counts}")
            for problem in report.problems:
                print(f"      - {problem}")
    manifest_problems = [] if args.tasks else check_manifest(tasks, MANIFEST_PATH)
    if args.json:
        print(json.dumps({"tasks": results, "manifest_problems": manifest_problems}, indent=2))
    else:
        print(f"\n{len(tasks) - failures}/{len(tasks)} fixtures valid")
        for problem in manifest_problems:
            print(f"manifest: {problem}")
        if not manifest_problems and not args.tasks:
            print("manifest: up to date")
    return 1 if failures or manifest_problems else 0


def cmd_build_fixtures(args: argparse.Namespace, settings: Settings) -> int:
    tasks = list_tasks(FIRST_PARTY_TASKS)
    for task in tasks:
        write_solution_patch(task)
    write_manifest(tasks, MANIFEST_PATH)
    print(
        f"wrote solution.patch for {len(tasks)} tasks and {MANIFEST_PATH.relative_to(PROJECT_ROOT)}"
    )
    return 0


def cmd_eval_retrieval(args: argparse.Namespace, settings: Settings) -> int:
    result = evaluate_retrieval(list_tasks(settings.tasks_dir), settings.allowed_roots)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"{'task':<34} {'gold file':<24} {'rank':>4}  {'cands':>5}")
    for row in result["tasks"]:
        for gold, rank in row["gold_ranks"].items():
            print(f"{row['task_id']:<34} {gold:<24} {rank or '-':>4}  {row['candidates']:>5}")
    agg = result["aggregate"]
    print(
        f"\nretrieval   recall@1={agg['recall@1']:.2f}  recall@3={agg['recall@3']:.2f}  "
        f"recall@5={agg['recall@5']:.2f}  MRR={agg['mrr']:.2f}  (n={agg['tasks']})"
    )
    print(
        f"random      recall@1={agg['random_recall@1']:.2f}  "
        f"recall@3={agg['random_recall@3']:.2f}  "
        f"recall@5={agg['random_recall@5']:.2f}  (expected, uniform ordering of non-test files)"
    )
    return 0


def cmd_serve(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    from .api import create_app

    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            "warning: the API has no authentication; binding to a non-loopback address exposes it",
            file=sys.stderr,
        )
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coderepair", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("tasks", help="list benchmark tasks")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_tasks)

    p = sub.add_parser("show", help="show a task's issue, parsed hints and agent-visible files")
    p.add_argument("task")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("search", help="read-only search in a task repository")
    p.add_argument("task")
    p.add_argument("query")
    p.add_argument("--regex", action="store_true", help="treat QUERY as a regular expression")
    p.add_argument("--symbol", action="store_true", help="look up a Python symbol definition")
    p.add_argument("--glob", help="only search paths matching this glob")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("retrieve", help="rank files for a task's issue, with reasons")
    p.add_argument("task")
    p.add_argument("-n", type=int, default=8)
    p.set_defaults(func=cmd_retrieve)

    p = sub.add_parser(
        "propose", help="propose a patch and display the diff (never writes to the repo)"
    )
    p.add_argument("task", nargs="?")
    p.add_argument("--repo", help="local repository path (must be under CODEREPAIR_ALLOWED_ROOTS)")
    p.add_argument("--issue", help="issue text file to use with --repo")
    p.add_argument("--backend", choices=BACKEND_NAMES)
    p.add_argument(
        "--script", type=Path, help="JSON list of canned responses for --backend scripted"
    )
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--no-save", action="store_true", help="do not write run artifacts")
    p.set_defaults(func=cmd_propose)

    p = sub.add_parser(
        "validate-fixtures", help="check the seeded-bug fixtures (runs first-party tests)"
    )
    p.add_argument("tasks", nargs="*")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate_fixtures)

    p = sub.add_parser("build-fixtures", help="regenerate solution.patch files and the manifest")
    p.set_defaults(func=cmd_build_fixtures)

    p = sub.add_parser("eval-retrieval", help="measure retrieval recall against gold files")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_eval_retrieval)

    p = sub.add_parser("serve", help="run the local API and diff viewer")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    try:
        return args.func(args, settings)
    except (TaskError, PolicyError, BackendError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
