"""Milestone 5: comparative benchmark of repair agents under equal budgets.

Agents (all share the issue, the snapshot, the patch policy and the budget):

``direct``
    Issue plus repository files in path order (no retrieval, no repository
    map). Up to ``max_calls`` independent samples; the first statically valid
    patch is submitted. Never runs tests.
``retrieval``
    Ranked, explained context (the Milestone 1 prompt). Up to ``max_calls``
    independent samples; the first statically valid patch is submitted. Never
    runs tests.
``feedback``
    The Milestone 3 loop: retrieval context, sandboxed visible tests after every
    valid patch, validation errors and test failures fed back, up to
    ``max_calls`` attempts; the top-ranked candidate (Milestone 4 scorecards)
    is submitted.
``feedback-sampled`` (ablation, not run by default)
    ``feedback`` whose retries sample like the sampling agents' later samples
    (``sample_index`` 1, 2, ...) instead of repeating the deterministic request.
    ``feedback`` versus ``retrieval`` changes two things at once (test feedback
    and no sampling); this agent changes only the first.

Every submitted patch is scored by the harness with the hidden tests in the
sandbox. ``pass@1`` is whether the agent's *first* model call alone would have
resolved the task. Token counts come from the backend (estimates for mocks).
"""

from __future__ import annotations

import hashlib
import json
import platform
import statistics
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

from ..agent import STATUS_PROPOSED, AttemptResult, attempt_proposal, build_context
from ..config import Limits
from ..issue import parse_issue
from ..llm.base import LLMBackend
from ..loop import RepairBudget, repair
from ..patch import PatchPolicy
from ..prompting import build_direct_prompt
from ..repo import ingest_repository
from ..sandbox.base import Sandbox, SandboxLimits
from ..trace import Trace, new_run_id
from .evaluate import PatchEvaluation, evaluate_patch
from .manifest import task_fingerprint
from .stats import format_p, paired_comparisons, sign_flip_test, wilson_interval
from .tasks import TaskSpec

AGENTS = ("direct", "retrieval", "feedback")  # the default comparison
ALL_AGENTS = (*AGENTS, "feedback-sampled")


@dataclass(frozen=True)
class BenchBudget:
    max_calls: int = 3
    max_tokens: int = 60_000
    max_wall_s: float = 900.0


@dataclass
class BenchRow:
    suite: str
    task_id: str
    agent: str
    backend: str
    model: str
    status: str  # resolved | unresolved | no-patch | error
    resolved: bool
    pass_at_1: bool
    failure: str  # "" when resolved
    calls: int
    input_tokens: int
    output_tokens: int
    llm_latency_s: float
    wall_s: float
    f2p_passing: str
    p2p_broken: int
    diff_lines: int
    detail: str = ""
    #: content hash of the task (repo, issue, tests, solution) the row was produced on
    task_hash: str = ""

    def key(self) -> tuple[str, str]:
        return (self.task_id, self.agent)


def _tokens(attempts: list[AttemptResult]) -> tuple[int, int, float]:
    inp = sum((a.response.input_tokens or 0) for a in attempts if a.response)
    out = sum((a.response.output_tokens or 0) for a in attempts if a.response)
    lat = sum(a.response.latency_s for a in attempts if a.response)
    return inp, out, lat


def classify_invalid(errors: list[str]) -> str:
    text = " ".join(errors)
    if "sandbox error" in text or "test run failed to start" in text:
        return "sandbox-error"
    if "backend error" in text:
        return "backend-error"
    if "could not parse" in text:
        return "invalid-output"
    if "no edits" in text:
        return "no-edits"
    if "not found" in text or "ambiguous" in text:
        return "anchor-mismatch"
    if "invalid Python" in text or "unparseable Python" in text:
        return "syntax-error"
    if "protected path" in text or "traversal" in text or "does not exist" in text:
        return "policy-violation"
    return "invalid-patch"


def classify_evaluation(evaluation: PatchEvaluation) -> str:
    if evaluation.resolved:
        return ""
    if evaluation.sandbox is not None and evaluation.sandbox.limit_exceeded:
        return "resource-limit"
    if any(o != "passed" for o in evaluation.fail_to_pass.values()):
        return "wrong-fix"
    if evaluation.pass_to_pass_broken:
        return "regression"
    return "untrustworthy-results"


def _sampling_agent(
    agent: str,
    task: TaskSpec,
    backend: LLMBackend,
    budget: BenchBudget,
    limits: Limits,
) -> tuple[list[AttemptResult], AttemptResult | None]:
    snapshot = ingest_repository(task.repo_dir, (task.dir,), limits)
    trace = Trace(new_run_id(f"bench_{agent}_{task.id}"))
    if agent == "direct":
        request = build_direct_prompt(snapshot, parse_issue(task.read_issue()), limits).request
    else:
        request = build_context(snapshot, task.read_issue(), limits, trace).bundle.request
    policy = PatchPolicy.from_limits(limits)
    attempts: list[AttemptResult] = []
    started = time.monotonic()
    for i in range(budget.max_calls):
        if i and (
            sum(_tokens(attempts)[:2]) >= budget.max_tokens
            or time.monotonic() - started >= budget.max_wall_s
        ):
            break
        result = attempt_proposal(
            replace(request, sample_index=i), backend, snapshot, policy, trace
        )
        attempts.append(result)
        if result.status == STATUS_PROPOSED or result.backend_error is not None:
            break
    chosen = next((a for a in attempts if a.status == STATUS_PROPOSED), None)
    return attempts, chosen


def run_agent(
    agent: str,
    task: TaskSpec,
    backend: LLMBackend,
    sandbox: Sandbox,
    *,
    suite: str,
    budget: BenchBudget,
    limits: Limits | None = None,
    sandbox_limits: SandboxLimits | None = None,
) -> BenchRow:
    limits = limits or Limits()
    started = time.monotonic()
    first: AttemptResult | None
    if agent in ("direct", "retrieval"):
        attempts, chosen = _sampling_agent(agent, task, backend, budget, limits)
        first = attempts[0] if attempts else None
        overlay = dict(chosen.patch.changed_files) if chosen else None
        last_errors = attempts[-1].errors if attempts else ["no attempts"]
    elif agent in ("feedback", "feedback-sampled"):
        snapshot = ingest_repository(task.repo_dir, (task.dir,), limits)
        run = repair(
            snapshot,
            task.read_issue(),
            backend,
            sandbox,
            # Same call budget as the sampling agents: no extra samples, no reproduction
            # test (candidates=1, repro_test=False), so every model call is a loop attempt.
            budget=RepairBudget(
                max_attempts=budget.max_calls,
                max_total_tokens=budget.max_tokens,
                max_wall_s=budget.max_wall_s,
                candidates=1,
                repro_test=False,
                sample_retries=agent == "feedback-sampled",
            ),
            limits=limits,
            sandbox_limits=sandbox_limits,
            task_id=task.id,
        )
        attempts = [a.result for a in run.attempts] + list(run.samples)
        first = run.attempts[0].result if run.attempts else None
        overlay = run.selected.candidate.changed_files if run.selected else None
        last_errors = (attempts[-1].errors if attempts else []) or [run.stop_reason]
        if overlay is None and "sandbox" in run.stop_reason:
            last_errors = [f"sandbox error: {run.stop_reason}"]
    else:
        raise ValueError(f"unknown agent {agent!r}")

    inp, out, lat = _tokens(attempts)
    row = BenchRow(
        suite=suite,
        task_id=task.id,
        agent=agent,
        backend=backend.name,
        model=backend.model,
        status="no-patch",
        resolved=False,
        pass_at_1=False,
        failure="",
        calls=len(attempts),
        input_tokens=inp,
        output_tokens=out,
        llm_latency_s=round(lat, 2),
        wall_s=0.0,
        f2p_passing="",
        p2p_broken=0,
        diff_lines=0,
    )
    if overlay is None:
        row.failure = classify_invalid(last_errors)
        row.detail = "; ".join(last_errors)[:300]
        if row.failure in ("backend-error", "sandbox-error"):
            row.status = "error"
    else:
        evaluation = evaluate_patch(task, overlay, sandbox, limits=sandbox_limits)
        row.resolved = evaluation.resolved
        row.status = "resolved" if evaluation.resolved else "unresolved"
        row.failure = classify_evaluation(evaluation)
        row.detail = evaluation.reason
        passing = sum(o == "passed" for o in evaluation.fail_to_pass.values())
        row.f2p_passing = f"{passing}/{len(evaluation.fail_to_pass)}"
        row.p2p_broken = len(evaluation.pass_to_pass_broken)
        row.diff_lines = sum(
            1
            for line in _diff_for(task, overlay, limits).splitlines()
            if line[:1] in "+-" and not line.startswith(("+++", "---"))
        )
        if first is not None and first.status == STATUS_PROPOSED:
            if first.patch.changed_files == overlay:
                row.pass_at_1 = evaluation.resolved
            else:
                row.pass_at_1 = evaluate_patch(
                    task, first.patch.changed_files, sandbox, limits=sandbox_limits
                ).resolved
    row.wall_s = round(time.monotonic() - started, 2)
    return row


def _diff_for(task: TaskSpec, overlay: dict[str, str], limits: Limits) -> str:
    from ..patch import unified_diff

    snapshot = ingest_repository(task.repo_dir, (task.dir,), limits)
    return unified_diff({p: snapshot.text(p) for p in overlay}, overlay)


# ------------------------------------------------------------------- aggregation


def task_hash(task: TaskSpec) -> str:
    return hashlib.sha256(json.dumps(task_fingerprint(task), sort_keys=True).encode()).hexdigest()[
        :16
    ]


def config_fingerprint(meta: dict) -> str:
    # The agent list is deliberately not part of it: a row depends only on its own
    # agent, so adding an agent to an existing results file reuses the other rows.
    keys = ("backend", "model", "budget", "sandbox", "sandbox_limits")
    return hashlib.sha256(
        json.dumps({k: meta[k] for k in keys}, sort_keys=True).encode()
    ).hexdigest()[:12]


def summarize(rows: list[BenchRow]) -> dict:
    out: dict = {}
    for agent in sorted(
        {r.agent for r in rows}, key=lambda a: ALL_AGENTS.index(a) if a in ALL_AGENTS else 99
    ):
        mine = [r for r in rows if r.agent == agent]
        by_suite = {}
        for suite in sorted({r.suite for r in mine}):
            suite_rows = [r for r in mine if r.suite == suite]
            by_suite[suite] = {
                "tasks": len(suite_rows),
                "resolved": sum(r.resolved for r in suite_rows),
            }
        n = len(mine)
        resolved = sum(r.resolved for r in mine)
        out[agent] = {
            "tasks": n,
            "resolved": resolved,
            "resolve_rate": round(resolved / n, 3) if n else 0.0,
            "resolve_ci95": [round(x, 3) for x in wilson_interval(resolved, n)],
            "pass_at_1": sum(r.pass_at_1 for r in mine),
            "valid_patch": sum(r.status in ("resolved", "unresolved") for r in mine),
            "regressions": sum(r.p2p_broken > 0 for r in mine),
            "mean_calls": round(statistics.mean(r.calls for r in mine), 2) if n else 0,
            "mean_tokens": round(statistics.mean(r.input_tokens + r.output_tokens for r in mine))
            if n
            else 0,
            "median_llm_latency_s": round(statistics.median(r.llm_latency_s for r in mine), 1)
            if n
            else 0,
            "median_wall_s": round(statistics.median(r.wall_s for r in mine), 1) if n else 0,
            "failures": dict(Counter(r.failure for r in mine if r.failure)),
            "by_suite": by_suite,
        }
    return out


def paired(rows: list[BenchRow], agents: list[str]) -> list[dict]:
    """Exact McNemar comparison of every pair of agents on the tasks both ran."""
    outcomes: dict[str, dict[str, bool]] = {}
    for r in rows:
        outcomes.setdefault(r.agent, {})[r.task_id] = r.resolved
    return [
        {
            "a": c.a,
            "b": c.b,
            "tasks": c.tasks,
            "both": c.both,
            "only_a": c.only_a,
            "only_b": c.only_b,
            "neither": c.neither,
            "p_value": round(c.p_value, 4),
        }
        for c in paired_comparisons(outcomes, agents)
    ]


def render_markdown(meta: dict, summary: dict, rows: list[BenchRow]) -> str:
    lines = [
        f"Backend `{meta['backend']}` / model `{meta['model']}`, budget {meta['budget']}, "
        f"{meta['date']}, {meta['machine']}, sandbox `{meta['sandbox']}`.",
        "",
        "| Agent | Resolved | 95% CI | pass@1 | Valid patch | Regressions | Mean calls | "
        "Mean tokens | Median LLM s | Median wall s |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for agent, s in summary.items():
        lo, hi = wilson_interval(s["resolved"], s["tasks"])
        lines.append(
            f"| {agent} | {s['resolved']}/{s['tasks']} | {100 * lo:.0f}–{100 * hi:.0f}% | "
            f"{s['pass_at_1']}/{s['tasks']} | "
            f"{s['valid_patch']}/{s['tasks']} | {s['regressions']} | {s['mean_calls']} | "
            f"{s['mean_tokens']} | {s['median_llm_latency_s']} | {s['median_wall_s']} |"
        )
    comparisons = paired(rows, list(summary))
    if comparisons:
        lines += [
            "",
            "Paired comparison on the same tasks (`Only A` / `Only B`: tasks exactly one of the "
            "two agents resolved):",
            "",
            *_paired_table(comparisons),
        ]
    lines += ["", "| Task | " + " | ".join(summary) + " |", "|---|" + "---|" * len(summary)]
    for task_id in sorted({r.task_id for r in rows}):
        cells = []
        for agent in summary:
            row = next((r for r in rows if r.task_id == task_id and r.agent == agent), None)
            cells.append("-" if row is None else ("resolved" if row.resolved else row.failure))
        lines.append(f"| {task_id} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def run_benchmark(
    tasks: list[tuple[str, TaskSpec]],
    agents: tuple[str, ...],
    backend_for: Callable[[TaskSpec], LLMBackend],
    sandbox: Sandbox,
    *,
    out_path: Path,
    budget: BenchBudget,
    limits: Limits | None = None,
    sandbox_limits: SandboxLimits | None = None,
    progress=print,
) -> dict:
    """Run every (task, agent) pair, appending rows to ``out_path`` (JSONL) as they finish.

    ``backend_for(task)`` returns the backend to use for a task (one shared
    instance for real models; a per-task instance for the oracle and scripted
    mocks). Re-running with the same configuration resumes: finished pairs are
    skipped.
    """
    backend = backend_for(tasks[0][1])
    meta = {
        "kind": "comparative benchmark",
        "backend": backend.name,
        "model": backend.model,
        "is_mock": backend.is_mock,
        "budget": asdict(budget),
        "agents": list(agents),
        "sandbox": sandbox.name,
        "sandbox_limits": asdict(sandbox_limits or SandboxLimits()),
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": f"{platform.system()} {platform.machine()} / Python {platform.python_version()}",
    }
    fingerprint = config_fingerprint(meta)
    hashes = {task.id: task_hash(task) for _, task in tasks}
    wanted = {(task.id, agent) for _, task in tasks for agent in agents}
    done: dict[tuple[str, str], BenchRow] = {}
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                row = BenchRow(**record["row"])
            except (ValueError, KeyError, TypeError):
                continue  # e.g. a line truncated by an interrupted run
            # Reuse only rows from the same configuration, on unchanged task content,
            # for the (task, agent) pairs requested now.
            if (
                record.get("config") == fingerprint
                and row.key() in wanted
                and row.task_hash == hashes.get(row.task_id)
            ):
                done[row.key()] = row
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as fh:
        for suite, task in tasks:
            for agent in agents:
                if (task.id, agent) in done:
                    continue
                try:
                    row = run_agent(
                        agent,
                        task,
                        backend_for(task),
                        sandbox,
                        suite=suite,
                        budget=budget,
                        limits=limits,
                        sandbox_limits=sandbox_limits,
                    )
                except Exception as exc:  # noqa: BLE001 - one bad row must not end the run
                    row = _error_row(suite, task, agent, backend, exc)
                row.task_hash = hashes[task.id]
                done[row.key()] = row
                fh.write(json.dumps({"config": fingerprint, "row": asdict(row)}) + "\n")
                fh.flush()
                progress(
                    f"{task.id:<34} {agent:<16} {row.status:<10} {row.failure:<16} "
                    f"calls={row.calls} tokens={row.input_tokens + row.output_tokens} "
                    f"llm={row.llm_latency_s}s"
                )
    rows = [done[key] for key in sorted(done)]
    return {
        "meta": meta,
        "config": fingerprint,
        "summary": summarize(rows),
        "paired": paired(rows, list(agents)),
        "rows": rows,
    }


def _error_row(suite: str, task: TaskSpec, agent: str, backend: LLMBackend, exc: Exception):
    return BenchRow(
        suite=suite,
        task_id=task.id,
        agent=agent,
        backend=backend.name,
        model=backend.model,
        status="error",
        resolved=False,
        pass_at_1=False,
        failure="harness-error",
        calls=0,
        input_tokens=0,
        output_tokens=0,
        llm_latency_s=0.0,
        wall_s=0.0,
        f2p_passing="",
        p2p_broken=0,
        diff_lines=0,
        detail=f"{type(exc).__name__}: {exc}"[:300],
    )


# ------------------------------------------------------------------- reports


def load_rows(path: Path) -> tuple[str, list[BenchRow]]:
    """Rows of the most recent configuration in a results JSONL (last row per pair wins)."""
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
            records.append((record["config"], BenchRow(**record["row"])))
        except (ValueError, KeyError, TypeError):
            continue
    if not records:
        return "", []
    config = records[-1][0]
    latest = {row.key(): row for cfg, row in records if cfg == config}
    return config, [latest[k] for k in sorted(latest)]


def render_report(paths: list[Path], current_hashes: dict[str, str] | None = None) -> str:
    """Per-file summaries with confidence intervals, plus a test pooled over files.

    ``current_hashes`` (task id -> task hash) drops rows produced on task content
    that has since changed, as resuming a run would. The pooled comparison keeps
    every task as one unit: per task it sums (A resolved) - (B resolved) over the
    files and applies an exact sign-flip test, so several models or seeds on the
    same tasks add evidence without being counted as independent tasks.
    """
    lines: list[str] = []
    per_task: dict[tuple[str, str], dict[str, int]] = {}  # (agent, task) -> file -> resolved
    agents: list[str] = []
    for index, path in enumerate(paths):
        config, rows = load_rows(path)
        if current_hashes is not None:
            stale = [r for r in rows if r.task_hash != current_hashes.get(r.task_id)]
            rows = [r for r in rows if r.task_hash == current_hashes.get(r.task_id)]
        else:
            stale = []
        if not rows:
            lines += [f"## {path.name}", "", "no current rows", ""]
            continue
        summary = summarize(rows)
        lines += [f"## {path.name}: `{rows[0].backend}` / `{rows[0].model}` (config {config})", ""]
        if stale:
            lines += [f"{len(stale)} rows on outdated task content were left out.", ""]
        lines += ["| Agent | Resolved | 95% CI | Valid patch |", "|---|---|---|---|"]
        for agent, s in summary.items():
            lo, hi = wilson_interval(s["resolved"], s["tasks"])
            lines.append(
                f"| {agent} | {s['resolved']}/{s['tasks']} | {100 * lo:.0f}–{100 * hi:.0f}% | "
                f"{s['valid_patch']}/{s['tasks']} |"
            )
        lines += [""] + _paired_table(paired(rows, list(summary))) + [""]
        for row in rows:
            per_task.setdefault((row.agent, row.task_id), {})[str(index)] = int(row.resolved)
            if row.agent not in agents:
                agents.append(row.agent)
    if len(paths) > 1:
        agents.sort(key=lambda a: ALL_AGENTS.index(a) if a in ALL_AGENTS else 99)
        lines += ["## Pooled over all files (one unit per task)", ""]
        lines += ["| Agent | Resolved runs |", "|---|---|"]
        for agent in agents:
            runs = [v for (a, _), files in per_task.items() if a == agent for v in files.values()]
            lines.append(f"| {agent} | {sum(runs)}/{len(runs)} |")
        lines += [
            "",
            "| A vs B | Tasks | Runs | A − B (resolved runs) | p (exact sign-flip, by task) |",
            "|---|---|---|---|---|",
        ]
        tasks = sorted({t for (_, t) in per_task})
        for a, b in combinations(agents, 2):
            diffs, runs = [], 0
            for task in tasks:
                fa, fb = per_task.get((a, task), {}), per_task.get((b, task), {})
                shared = set(fa) & set(fb)
                if shared:
                    runs += len(shared)
                    diffs.append(sum(fa[f] - fb[f] for f in shared))
            lines.append(
                f"| {a} vs {b} | {len(diffs)} | {runs} | {sum(diffs):+d} | "
                f"{format_p(sign_flip_test(diffs))} |"
            )
        lines += [
            "",
            "Confidence intervals are not pooled: runs of the same task are correlated.",
            "",
        ]
    return "\n".join(lines)


def _paired_table(comparisons: list[dict]) -> list[str]:
    out = ["| A vs B | Tasks | Only A | Only B | p (exact McNemar) |", "|---|---|---|---|---|"]
    for c in comparisons:
        out.append(
            f"| {c['a']} vs {c['b']} | {c['tasks']} | {c['only_a']} | {c['only_b']} | "
            f"{format_p(c['p_value'])} |"
        )
    return out
