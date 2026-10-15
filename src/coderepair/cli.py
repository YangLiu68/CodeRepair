"""Command-line interface: ``coderepair <command>``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .agent import STATUS_PROPOSED, ProposalRun, propose_patch
from .approval import ApprovalError, apply_approved, approve, resolve_run_dir, risks_of
from .backends import BACKEND_NAMES, make_backend
from .benchmark.compare import AGENTS, BenchBudget, render_markdown, run_benchmark
from .benchmark.evaluate import evaluate_patch
from .benchmark.manifest import check_manifest, write_manifest, write_solution_patch
from .benchmark.retrieval_eval import evaluate_retrieval
from .benchmark.tasks import TaskError, list_tasks, load_any_task
from .benchmark.validate import SandboxFixtureRunner, validate_task
from .config import PROJECT_ROOT, Settings
from .execution import describe_result
from .issue import parse_issue
from .llm.base import BackendError
from .loop import RepairBudget, RepairRun, repair
from .repo import ingest_repository
from .retrieval import rank_files
from .sandbox.base import Sandbox, SandboxError
from .sandbox.bundle import ensure_runner_bundle
from .sandbox.docker import DockerSandbox
from .sandbox.factory import SANDBOX_NAMES, make_sandbox, sandbox_status
from .sandbox.probes import PROBES, run_probes
from .search import RepoIndex
from .security import PolicyError

FIRST_PARTY_TASKS = PROJECT_ROOT / "benchmarks" / "tasks"
PUBLIC_TASKS = PROJECT_ROOT / "benchmarks" / "public"
SUITES = {
    "fixtures": (FIRST_PARTY_TASKS, PROJECT_ROOT / "benchmarks" / "manifest.json"),
    "public": (PUBLIC_TASKS, PUBLIC_TASKS / "manifest.json"),
}
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


def _make_sandbox(args: argparse.Namespace, settings: Settings) -> Sandbox:
    sandbox = make_sandbox(
        getattr(args, "sandbox", None) or settings.sandbox,
        settings.cache_dir,
        settings.sandbox_image,
    )
    if sandbox.name != "docker":
        print(f"NOTE: tests run in: {sandbox.isolation}", file=sys.stderr)
    return sandbox


def _snapshot_for_task(settings: Settings, task_id: str):
    task = load_any_task(settings.task_dirs, task_id)
    return task, ingest_repository(task.repo_dir, settings.allowed_roots, settings.limits)


# ----------------------------------------------------------------------- commands


def cmd_tasks(args: argparse.Namespace, settings: Settings) -> int:
    tasks = [t for d in settings.task_dirs for t in list_tasks(d)]
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
    if run.tests is not None:
        print(f"\nvisible tests on the patched copy: {describe_result(run.tests)}")
    if run.run_dir:
        print(f"artifacts: {run.run_dir}")


def cmd_propose(args: argparse.Namespace, settings: Settings) -> int:
    backend_name = args.backend or settings.backend
    task = None
    if args.task:
        task = load_any_task(settings.task_dirs, args.task)
        snapshot = ingest_repository(task.repo_dir, settings.allowed_roots, settings.limits)
        issue_text = task.read_issue()
    else:
        if not (args.repo and args.issue):
            print("error: give a TASK id, or both --repo and --issue", file=sys.stderr)
            return 2
        snapshot = ingest_repository(args.repo, settings.allowed_roots, settings.limits)
        issue_text = Path(args.issue).read_text(encoding="utf-8")
    backend = make_backend(backend_name, settings, task=task, script_path=args.script)
    sandbox = _make_sandbox(args, settings) if args.run_tests else None
    run = propose_patch(
        snapshot,
        issue_text,
        backend,
        limits=settings.limits,
        runs_dir=None if args.no_save else settings.runs_dir,
        task_id=task.id if task else None,
        sandbox=sandbox,
        sandbox_limits=settings.sandbox_limits(),
    )
    if args.json:
        print(json.dumps({**run.summary_dict(), "diff": run.diff}, indent=2))
    else:
        _print_run(run, _use_color(args))
    return 0 if run.status == STATUS_PROPOSED else 1


def cmd_evaluate(args: argparse.Namespace, settings: Settings) -> int:
    """Propose a patch for a benchmark task and score it with the hidden tests."""
    task, snapshot = _snapshot_for_task(settings, args.task)
    backend = make_backend(
        args.backend or settings.backend, settings, task=task, script_path=args.script
    )
    sandbox = _make_sandbox(args, settings)
    run = propose_patch(
        snapshot,
        task.read_issue(),
        backend,
        limits=settings.limits,
        runs_dir=None if args.no_save else settings.runs_dir,
        task_id=task.id,
    )
    evaluation = None
    if run.status == STATUS_PROPOSED and run.patch is not None:
        evaluation = evaluate_patch(
            task, run.patch.changed_files, sandbox, limits=settings.sandbox_limits()
        )
        if run.run_dir is not None:
            (run.run_dir / "evaluation.json").write_text(
                json.dumps(evaluation.to_dict(), indent=2) + "\n", encoding="utf-8"
            )
    if args.json:
        print(
            json.dumps(
                {**run.summary_dict(), "evaluation": evaluation.to_dict() if evaluation else None},
                indent=2,
            )
        )
    else:
        _print_run(run, _use_color(args))
        if evaluation is None:
            print("\nevaluation: not run (no valid patch was proposed)")
        else:
            print(f"\nevaluation: {evaluation.status.upper()} - {evaluation.reason}")
            for test_id, outcome in evaluation.fail_to_pass.items():
                print(f"  fail-to-pass  {outcome:<8} {test_id}")
            for test_id, outcome in evaluation.pass_to_pass_broken.items():
                print(f"  BROKEN        {outcome:<8} {test_id}")
            if evaluation.sandbox:
                print(f"  sandbox: {evaluation.sandbox.isolation}")
    return 0 if evaluation is not None and evaluation.resolved else 1


def _print_repair(run: RepairRun, color: bool) -> None:
    banner = _YELLOW if color else ""
    reset = _RESET if color else ""
    if run.backend == "oracle":
        print(f"{banner}NOTE: 'oracle' replays the gold solution; NOT a repair result.{reset}\n")
    elif run.is_mock:
        print(f"{banner}NOTE: '{run.backend}' is a mock backend (canned responses).{reset}\n")
    print(f"run:       {run.run_id}")
    print(f"backend:   {run.backend} ({run.model})")
    print(f"sandbox:   {run.isolation}")
    if run.baseline is not None:
        print(f"baseline:  {describe_result(run.baseline).splitlines()[0]}")
    for attempt in run.attempts:
        print(f"attempt {attempt.index}: {attempt.verdict}")
    if run.repro is not None:
        print(f"reproduction test: {run.repro.status} - {run.repro.detail}")
    if run.scorecards:
        print("\ncandidates (ranked):")
        for card in run.scorecards:
            print(f"  #{card.rank} candidate {card.candidate.index} ({card.candidate.source})")
            print(f"       {'; '.join(card.reasons())}")
    print(f"\nstatus:    {run.status} ({run.stop_reason})")
    print(f"tokens:    {run.tokens_used}")
    for warning in run.warnings:
        print(f"{banner}warning:{reset}   {warning}")
    if run.diff:
        top = run.selected
        print(f"\nselected: candidate {top.candidate.index} ({top.candidate.source})\n")
        print(colorize_diff(run.diff, color), end="")
        print("\nNothing was written to the repository; review the diff above.")
    if run.run_dir:
        print(f"artifacts: {run.run_dir}")
        if run.diff:
            print(f"approve:   coderepair approve {run.run_id} --reviewer <name> [--candidate N]")


def cmd_repair(args: argparse.Namespace, settings: Settings) -> int:
    """Iterative repair: propose, test in the sandbox, feed failures back, retry."""
    task = None
    if args.task:
        task, snapshot = _snapshot_for_task(settings, args.task)
        issue_text = task.read_issue()
    else:
        if not (args.repo and args.issue):
            print("error: give a TASK id, or both --repo and --issue", file=sys.stderr)
            return 2
        snapshot = ingest_repository(args.repo, settings.allowed_roots, settings.limits)
        issue_text = Path(args.issue).read_text(encoding="utf-8")
    if args.evaluate and task is None:
        print("error: --evaluate needs a benchmark TASK id", file=sys.stderr)
        return 2
    backend = make_backend(
        args.backend or settings.backend, settings, task=task, script_path=args.script
    )
    sandbox = _make_sandbox(args, settings)
    run = repair(
        snapshot,
        issue_text,
        backend,
        sandbox,
        budget=RepairBudget(
            max_attempts=args.max_attempts,
            candidates=args.candidates,
            repro_test=args.repro_test,
        ),
        limits=settings.limits,
        sandbox_limits=settings.sandbox_limits(),
        runs_dir=None if args.no_save else settings.runs_dir,
        task_id=task.id if task else None,
    )
    evaluation = None
    if args.evaluate and run.selected is not None:
        evaluation = evaluate_patch(
            task, run.selected.candidate.changed_files, sandbox, limits=settings.sandbox_limits()
        )
        if run.run_dir is not None:
            (run.run_dir / "evaluation.json").write_text(
                json.dumps(evaluation.to_dict(), indent=2) + "\n", encoding="utf-8"
            )
    if args.json:
        payload = {**run.summary_dict(), "diff": run.diff}
        if args.evaluate:
            payload["evaluation"] = evaluation.to_dict() if evaluation else None
        print(json.dumps(payload, indent=2))
    else:
        _print_repair(run, _use_color(args))
        if args.evaluate:
            if evaluation is None:
                print("\nevaluation: not run (no candidate patch)")
            else:
                print(
                    f"\nevaluation (hidden tests): {evaluation.status.upper()} - "
                    f"{evaluation.reason}"
                )
    if args.evaluate:
        return 0 if evaluation is not None and evaluation.resolved else 1
    return 0 if run.status in ("fixed", "unverified") else 1


def cmd_bench(args: argparse.Namespace, settings: Settings) -> int:
    """Milestone 5: run the comparative benchmark and write JSONL + summary + markdown."""
    agents = tuple(a.strip() for a in args.agents.split(",") if a.strip())
    unknown = [a for a in agents if a not in AGENTS]
    if unknown:
        print(f"error: unknown agent(s) {unknown}; choose from {AGENTS}", file=sys.stderr)
        return 2
    chosen = list(SUITES) if args.suite == "all" else [args.suite]
    tasks = []
    for suite in chosen:
        if SUITES[suite][0].is_dir():
            tasks += [(suite, t) for t in list_tasks(SUITES[suite][0])]
    if args.tasks:
        tasks = [(s, t) for s, t in tasks if t.id in set(args.tasks)]
    if not tasks:
        print("error: no tasks selected", file=sys.stderr)
        return 2
    backend_name = args.backend or settings.backend
    if backend_name == "oracle":
        print(
            "NOTE: the oracle backend replays gold solutions; this checks the harness only.",
            file=sys.stderr,
        )
    sandbox = _make_sandbox(args, settings)
    out = Path(args.out) if args.out else settings.runs_dir / "bench" / f"{backend_name}.jsonl"
    shared = (
        None if backend_name in ("oracle", "scripted") else make_backend(backend_name, settings)
    )

    def backend_for(task):
        return shared or make_backend(backend_name, settings, task=task, script_path=args.script)

    try:
        results = run_benchmark(
            tasks,
            agents,
            backend_for,
            sandbox,
            out_path=out,
            budget=BenchBudget(max_calls=args.max_calls),
            limits=settings.limits,
            sandbox_limits=settings.sandbox_limits(),
        )
    finally:
        unload = getattr(shared, "unload", None)
        if unload is not None:
            unload()
    summary_path = out.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps({k: v for k, v in results.items() if k != "rows"}, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown = render_markdown(results["meta"], results["summary"], results["rows"])
    out.with_suffix(".md").write_text(markdown, encoding="utf-8")
    print()
    print(markdown)
    print(f"rows: {out}\nsummary: {summary_path}")
    return 0


def cmd_review(args: argparse.Namespace, settings: Settings) -> int:
    run_dir = resolve_run_dir(settings.runs_dir, args.run_id)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    print(f"run {summary['run_id']}  task={summary.get('task_id')}  status={summary['status']}")
    print(f"backend: {summary['backend']} ({summary['model']})  sandbox: {summary.get('sandbox')}")
    repro = summary.get("reproduction_test")
    if repro:
        print(f"reproduction test: {repro['status']} - {repro['detail']}")
    for card in summary.get("candidates", []):
        print(f"\n#{card['rank']} candidate {card['candidate']} ({card['source']})")
        for reason in card["reasons"]:
            print(f"   - {reason}")
        for finding in card["security"]:
            print(f"   ! {finding}")
        for risk in risks_of(card):
            print(f"   risk: {risk}")
        patch = run_dir / f"candidate-{card['candidate']}.patch"
        print(colorize_diff(patch.read_text(encoding="utf-8"), _use_color(args)), end="")
    approval = run_dir / "approval.json"
    if approval.exists():
        record = json.loads(approval.read_text(encoding="utf-8"))
        print(
            f"\napproved: candidate {record['candidate']} by {record['reviewer']} "
            f"at {record['approved_at']}"
        )
    return 0


def cmd_approve(args: argparse.Namespace, settings: Settings) -> int:
    run_dir = resolve_run_dir(settings.runs_dir, args.run_id)
    record = approve(
        run_dir,
        candidate=args.candidate,
        reviewer=args.reviewer,
        acknowledge_risks=args.acknowledge_risks,
        include_reproduction_test=args.include_repro_test,
        note=args.note or "",
    )
    print(f"approved candidate {record.candidate} of {record.run_id} by {record.reviewer}")
    print(f"diff sha256: {record.diff_sha256}")
    for risk in record.acknowledged_risks:
        print(f"acknowledged risk: {risk}")
    print(f"patch: {run_dir / 'approved.patch'}")
    print(
        "Nothing has been written to the repository. To write the working tree (no commit, "
        f"no push): coderepair apply {record.run_id} --repo {record.repo_root}"
    )
    return 0


def cmd_apply(args: argparse.Namespace, settings: Settings) -> int:
    run_dir = resolve_run_dir(settings.runs_dir, args.run_id)
    result = apply_approved(
        run_dir,
        args.repo,
        allowed_roots=settings.allowed_roots,
        protected_roots=(FIRST_PARTY_TASKS,),
        limits=settings.limits,
    )
    print(f"wrote {len(result.written)} file(s) in {result.repo_root}:")
    for rel in result.written:
        print(f"  {rel}")
    print("No commit, push or merge was made. Inspect with: git -C <repo> diff")
    return 0


def cmd_sandbox(args: argparse.Namespace, settings: Settings) -> int:
    if args.action == "status":
        statuses = sandbox_status(settings.cache_dir, settings.sandbox_image)
        if args.json:
            print(json.dumps([vars(s) for s in statuses], indent=2))
            return 0
        for status in statuses:
            mark = "available  " if status.available else "unavailable"
            print(f"{status.name:<9} {mark} {status.detail}")
            print(f"          isolation: {status.isolation}")
        usable = [s.name for s in statuses if s.available]
        print(f"\n'auto' uses: {usable[0] if usable else 'nothing (tests will not run)'}")
        return 0
    if args.action == "pull":
        docker = DockerSandbox(
            ensure_runner_bundle(settings.cache_dir), image=settings.sandbox_image
        )
        proc = docker.pull()
        print(proc.stdout or proc.stderr)
        return proc.returncode
    sandbox = _make_sandbox(args, settings)
    reports = run_probes(sandbox, args.probe or None)
    if args.json:
        print(
            json.dumps(
                {
                    "sandbox": sandbox.name,
                    "isolation": sandbox.isolation,
                    "probes": [r.to_dict() for r in reports],
                },
                indent=2,
            )
        )
    else:
        print(f"sandbox: {sandbox.name} - {sandbox.isolation}\n")
        for report in reports:
            mark = "CONTAINED" if report.contained else "ESCAPED  "
            print(
                f"{mark}  {report.name:<15} {report.observed:<12} "
                f"{report.duration_s:5.1f}s  {report.threat}"
            )
            for detail in report.details:
                print(f"           - {detail}")
        contained = sum(r.contained for r in reports)
        print(f"\n{contained}/{len(reports)} probes contained")
    return 0 if all(r.contained for r in reports) else 1


def cmd_validate_fixtures(args: argparse.Namespace, settings: Settings) -> int:
    """Check benchmark tasks. First-party fixtures may run on the host (trusted);
    the public suite contains third-party code and always runs in a sandbox."""
    chosen = list(SUITES) if args.suite == "all" else [args.suite]
    failures = 0
    results = []
    manifest_problems = []
    total = 0
    for suite in chosen:
        root, manifest = SUITES[suite]
        tasks = list_tasks(root)
        if args.tasks:
            tasks = [t for t in tasks if t.id in set(args.tasks)]
        runner = None
        if args.sandbox or suite == "public":
            sandbox = _make_sandbox(argparse.Namespace(sandbox=args.sandbox), settings)
            runner = SandboxFixtureRunner(sandbox, settings.sandbox_limits())
        for task in tasks:
            report = validate_task(
                task,
                trusted_root=root,
                timeout_s=settings.fixture_test_timeout_s,
                runner=runner,
            )
            total += 1
            failures += not report.ok
            results.append(
                {
                    "suite": suite,
                    "task_id": task.id,
                    "ok": report.ok,
                    "problems": report.problems,
                    **report.counts,
                }
            )
            if not args.json:
                status = "PASS" if report.ok else "FAIL"
                counts = ", ".join(f"{k}={v}" for k, v in report.counts.items())
                print(f"{status}  {task.id:<34} {counts}")
                for problem in report.problems:
                    print(f"      - {problem}")
        if not args.tasks:
            manifest_problems += [f"{suite}: {p}" for p in check_manifest(tasks, manifest)]
    if args.json:
        print(json.dumps({"tasks": results, "manifest_problems": manifest_problems}, indent=2))
    else:
        print(f"\n{total - failures}/{total} tasks valid")
        for problem in manifest_problems:
            print(f"manifest: {problem}")
        if not manifest_problems and not args.tasks:
            print("manifest: up to date")
    return 1 if failures or manifest_problems else 0


def cmd_build_fixtures(args: argparse.Namespace, settings: Settings) -> int:
    for suite, (root, manifest) in SUITES.items():
        if not root.is_dir():
            continue
        tasks = list_tasks(root)
        for task in tasks:
            write_solution_patch(task)
        write_manifest(tasks, manifest)
        print(
            f"{suite}: wrote solution.patch for {len(tasks)} tasks and "
            f"{manifest.relative_to(PROJECT_ROOT)}"
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
    p.add_argument(
        "--run-tests",
        action="store_true",
        help="run the repository's visible tests on a patched copy inside a sandbox",
    )
    p.add_argument("--sandbox", choices=SANDBOX_NAMES, help="sandbox backend (default: auto)")
    p.set_defaults(func=cmd_propose)

    p = sub.add_parser(
        "repair", help="iterative repair: propose, test in a sandbox, feed failures back, retry"
    )
    p.add_argument("task", nargs="?")
    p.add_argument("--repo", help="local repository path (must be under CODEREPAIR_ALLOWED_ROOTS)")
    p.add_argument("--issue", help="issue text file to use with --repo")
    p.add_argument("--backend", choices=BACKEND_NAMES)
    p.add_argument("--script", type=Path)
    p.add_argument("--sandbox", choices=SANDBOX_NAMES)
    p.add_argument("--max-attempts", type=int, default=4)
    p.add_argument(
        "--candidates",
        type=int,
        default=1,
        help="aim for this many distinct passing candidates (extra samples after the loop)",
    )
    p.add_argument(
        "--repro-test",
        action="store_true",
        help="ask the model for a reproduction test and use it to rank candidates",
    )
    p.add_argument(
        "--evaluate", action="store_true", help="also score the best candidate with hidden tests"
    )
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--no-save", action="store_true")
    p.set_defaults(func=cmd_repair)

    p = sub.add_parser(
        "evaluate", help="propose a patch for a task and score it with hidden tests (sandboxed)"
    )
    p.add_argument("task")
    p.add_argument("--backend", choices=BACKEND_NAMES)
    p.add_argument("--script", type=Path)
    p.add_argument("--sandbox", choices=SANDBOX_NAMES)
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--no-save", action="store_true")
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("bench", help="comparative benchmark: direct vs retrieval vs feedback")
    p.add_argument("--suite", choices=("fixtures", "public", "all"), default="fixtures")
    p.add_argument("--tasks", nargs="*")
    p.add_argument("--agents", default=",".join(AGENTS))
    p.add_argument("--backend", choices=BACKEND_NAMES)
    p.add_argument("--script", type=Path)
    p.add_argument("--sandbox", choices=SANDBOX_NAMES)
    p.add_argument("--max-calls", type=int, default=3, help="model calls per agent per task")
    p.add_argument("--out", help="results JSONL (resumable); summary and markdown go next to it")
    p.set_defaults(func=cmd_bench)

    p = sub.add_parser("review", help="show a repair run's ranked candidates and scorecards")
    p.add_argument("run_id")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-color", action="store_true")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("approve", help="record a human approval for one candidate")
    p.add_argument("run_id")
    p.add_argument("--reviewer", required=True)
    p.add_argument("--candidate", type=int, help="default: the top-ranked candidate")
    p.add_argument("--acknowledge-risks", action="store_true")
    p.add_argument("--include-repro-test", action="store_true")
    p.add_argument("--note")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser(
        "apply", help="write an approved candidate into a local repo (no git, no commit, no push)"
    )
    p.add_argument("run_id")
    p.add_argument("--repo", required=True)
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("sandbox", help="sandbox status, abuse self-test, image pull")
    p.add_argument("action", choices=("status", "selftest", "pull"))
    p.add_argument("--sandbox", choices=SANDBOX_NAMES)
    p.add_argument("--probe", action="append", choices=[pr.name for pr in PROBES])
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_sandbox)

    p = sub.add_parser(
        "validate-fixtures", help="check the seeded-bug fixtures (runs first-party tests)"
    )
    p.add_argument("tasks", nargs="*")
    p.add_argument("--json", action="store_true")
    p.add_argument("--suite", choices=("fixtures", "public", "all"), default="fixtures")
    p.add_argument(
        "--sandbox",
        choices=SANDBOX_NAMES,
        help="run the fixture tests in a sandbox instead of on the host (always for public)",
    )
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
    except (TaskError, PolicyError, BackendError, SandboxError, ApprovalError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
