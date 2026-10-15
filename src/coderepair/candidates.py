"""Milestone 4: several candidate patches, a reproduction test, scorecards and ranking.

After the repair loop, CodeRepair can

1. draw extra independent samples until it has ``n`` candidates that pass the
   visible tests (or the budget runs out),
2. ask the model for a *reproduction test*: a new test module that must fail
   on the original code; a candidate is ``verified`` when that test passes on
   the patched code (all runs in the sandbox),
3. score every distinct valid candidate on visible tests, regressions against
   the baseline, the reproduction test, new lint and type errors and a
   security review of the diff, and
4. rank them with an explicit, explainable ordering.

The reproduction test is model-written code. It is parsed, restricted to
pytest + standard library + the repository's own modules, scanned for risky
calls, and executed only in the sandbox. It never replaces or edits existing
tests; it is offered to the reviewer as an optional new file.
"""

from __future__ import annotations

import ast
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from .agent import STATUS_PROPOSED, AttemptResult, RepairContext, attempt_proposal
from .checks import CheckResult, SecurityFinding, lint_delta, security_review, typecheck_delta
from .execution import run_repo_tests
from .llm.base import BackendError, LLMBackend
from .patch import PatchPolicy
from .prompting import build_repro_request
from .repo import RepoSnapshot
from .sandbox.base import Sandbox, SandboxError, SandboxLimits, SandboxResult
from .search import module_name
from .trace import Trace

REPRO_VERIFIED = "verified"  # fails on the original code, passes with the candidate
REPRO_FAILED = "still-failing"  # fails on the original code and with the candidate
REPRO_NA = "n/a"  # no usable reproduction test

MAX_REPRO_CHARS = 8_000
_ALLOWED_TEST_IMPORTS = {"pytest", "__future__"}
# Defence in depth only: the test runs in the sandbox regardless.
_FORBIDDEN_REPRO_MODULES = {
    "subprocess",
    "socket",
    "ctypes",
    "multiprocessing",
    "urllib",
    "http",
    "requests",
    "httpx",
    "pickle",
    "marshal",
    "importlib",
    "signal",
    "pty",
}
_FORBIDDEN_REPRO_CALLS = {"eval", "exec", "compile", "__import__", "breakpoint", "input"}
_FORBIDDEN_REPRO_ATTRS = {"system", "popen", "environ", "kill", "fork", "execv", "execve"}


@dataclass
class Candidate:
    index: int
    source: str  # "loop attempt 2", "sample 1"
    attempt: AttemptResult
    visible: SandboxResult | None = None

    @property
    def diff(self) -> str:
        return self.attempt.patch.diff if self.attempt.patch and self.attempt.patch.ok else ""

    @property
    def changed_files(self) -> dict[str, str]:
        return dict(self.attempt.patch.changed_files) if self.attempt.patch else {}


@dataclass
class ReproTest:
    status: str  # "reproduces" | "does-not-reproduce" | "invalid" | "unavailable"
    path: str = ""
    code: str = ""
    summary: str = ""
    detail: str = ""
    baseline: SandboxResult | None = None
    tokens: int = 0

    @property
    def usable(self) -> bool:
        return self.status == "reproduces"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "path": self.path,
            "summary": self.summary,
            "detail": self.detail,
            "code": self.code,
            "baseline": self.baseline.to_dict() if self.baseline else None,
        }


@dataclass
class Scorecard:
    candidate: Candidate
    fixes: list[str] = field(default_factory=list)
    regressions: list[str] = field(default_factory=list)
    visible_all_pass: bool = False
    repro: str = REPRO_NA
    lint: CheckResult | None = None
    types: CheckResult | None = None
    security: list[SecurityFinding] = field(default_factory=list)
    diff_lines: int = 0
    rank: int = 0
    #: Infrastructure problems while scoring (a sandbox that failed to start, ...).
    problems: list[str] = field(default_factory=list)

    @property
    def high_risk(self) -> list[SecurityFinding]:
        return [f for f in self.security if f.severity == "high"]

    def rank_key(self) -> tuple:
        repro_score = {REPRO_VERIFIED: 2, REPRO_NA: 1, REPRO_FAILED: 0}[self.repro]
        return (
            int(self.visible_all_pass),
            int(not self.regressions),
            repro_score,
            -len(self.high_risk),
            -len(self.types.new) if self.types else 0,
            -len(self.lint.new) if self.lint else 0,
            -(len(self.security) - len(self.high_risk)),
            -self.diff_lines,
            -self.candidate.index,
        )

    def reasons(self) -> list[str]:
        reasons = [
            "all visible tests pass" if self.visible_all_pass else "visible tests fail",
            f"fixes {len(self.fixes)} previously failing test(s)",
            f"{len(self.regressions)} regression(s)",
            f"reproduction test: {self.repro}",
        ]
        for check in (self.lint, self.types):
            if check is not None:
                new = f"{len(check.new)} new issue(s)" if check.status == "new-issues" else ""
                reasons.append(f"{check.tool}: {new or check.status}")
        medium = len(self.security) - len(self.high_risk)
        reasons.append(f"security: {len(self.high_risk)} high, {medium} medium")
        reasons.append(f"{self.diff_lines} changed line(s)")
        reasons += [f"scoring problem: {p}" for p in self.problems]
        return reasons

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "candidate": self.candidate.index,
            "source": self.candidate.source,
            "visible_all_pass": self.visible_all_pass,
            "fixes": self.fixes,
            "regressions": self.regressions,
            "reproduction_test": self.repro,
            "lint": self.lint.to_dict() if self.lint else None,
            "typecheck": self.types.to_dict() if self.types else None,
            "security": [str(f) for f in self.security],
            "diff_lines": self.diff_lines,
            "reasons": self.reasons(),
            "files_changed": sorted(self.candidate.changed_files),
            "warnings": self.candidate.attempt.warnings,
            "problems": self.problems,
        }


# ------------------------------------------------------------ reproduction tests


def _repo_modules(snapshot: RepoSnapshot) -> set[str]:
    tops = set()
    for path in snapshot.paths():
        mod = module_name(path)
        if mod:
            tops.add(mod.split(".")[0])
    return tops


def check_repro_code(code: str, snapshot: RepoSnapshot) -> str | None:
    """Return why the reproduction test is not acceptable, or None."""
    if len(code) > MAX_REPRO_CHARS:
        return f"test module longer than {MAX_REPRO_CHARS} characters"
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError) as exc:
        return f"test module is not valid Python: {exc}"
    tests = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name.startswith("test")
    ]
    if not tests:
        return "no top-level test functions"
    allowed = _ALLOWED_TEST_IMPORTS | _repo_modules(snapshot) | set(sys.stdlib_module_names)
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                return "relative imports are not allowed in the reproduction test"
            modules = [node.module or ""]
        for module in modules:
            top = module.split(".")[0]
            if top in _FORBIDDEN_REPRO_MODULES or top not in allowed:
                return f"import of {module!r} is not allowed in the reproduction test"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _FORBIDDEN_REPRO_CALLS:
                return f"call to {node.func.id}() is not allowed in the reproduction test"
        if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_REPRO_ATTRS:
            return f"use of .{node.attr} is not allowed in the reproduction test"
    return None


def repro_test_path(snapshot: RepoSnapshot) -> str:
    has_tests_dir = any(p.startswith("tests/") for p in snapshot.paths())
    return "tests/test_coderepair_repro.py" if has_tests_dir else "test_coderepair_repro.py"


def generate_repro_test(
    context: RepairContext,
    snapshot: RepoSnapshot,
    backend: LLMBackend,
    sandbox: Sandbox,
    trace: Trace,
    limits: SandboxLimits | None = None,
) -> ReproTest:
    request = build_repro_request(context.bundle)
    try:
        response = backend.complete(request)
    except BackendError as exc:
        trace.add("repro_error", error=str(exc))
        return ReproTest("unavailable", detail=f"backend error: {exc}")
    tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
    trace.add("repro_response", text=response.text, tokens=tokens)
    try:
        payload = json.loads(response.text)
        code, summary = str(payload["test_code"]), str(payload.get("summary", ""))
    except (ValueError, KeyError, TypeError, RecursionError) as exc:
        return ReproTest("invalid", detail=f"unparseable response: {exc}", tokens=tokens)
    path = repro_test_path(snapshot)
    if path in snapshot.files:
        return ReproTest("invalid", path=path, detail=f"{path} already exists", tokens=tokens)
    problem = check_repro_code(code, snapshot)
    if problem:
        trace.add("repro_rejected", reason=problem)
        return ReproTest("invalid", path, code, summary, problem, tokens=tokens)
    try:
        baseline = run_repo_tests(
            snapshot, sandbox, extra_files={path: code}, selectors=[path], limits=limits
        )
    except SandboxError as exc:
        trace.add("repro_error", error=str(exc))
        return ReproTest("unavailable", path, code, summary, f"sandbox error: {exc}", tokens=tokens)
    repro = ReproTest("does-not-reproduce", path, code, summary, baseline=baseline, tokens=tokens)
    results = baseline.results
    if baseline.limit_exceeded or results is None or baseline.problems:
        repro.status = "invalid"
        repro.detail = "the test session did not complete on the original code"
    elif results.collect_errors or not results.outcomes:
        repro.status = "invalid"
        repro.detail = "the test module could not be collected"
    elif results.ids_with("error"):
        repro.status = "invalid"
        repro.detail = "the tests error (not fail) on the original code"
    elif results.ids_with("failed"):
        repro.status = "reproduces"
        repro.detail = f"{len(results.ids_with('failed'))} test(s) fail on the original code"
    else:
        repro.detail = "all tests pass on the original code, so they do not reproduce the issue"
    trace.add("repro_baseline", status=repro.status, detail=repro.detail)
    return repro


# ---------------------------------------------------------------------- sampling


def sample_candidates(
    context: RepairContext,
    snapshot: RepoSnapshot,
    backend: LLMBackend,
    policy: PatchPolicy,
    trace: Trace,
    *,
    count: int,
    start_index: int,
    budget_left: Callable[[], bool] = lambda: True,
) -> list[AttemptResult]:
    """Independent samples from the base prompt (no feedback), for diversity.

    ``budget_left`` is checked before every call, so samples never overrun the run's
    token or time budget by more than one call."""
    samples = []
    for i in range(count):
        if not budget_left():
            trace.add("sample_skipped", reason="budget exhausted")
            break
        request = replace(context.bundle.request, sample_index=start_index + i)
        trace.add("sample_start", sample=start_index + i)
        samples.append(attempt_proposal(request, backend, snapshot, policy, trace))
        if samples[-1].backend_error is not None:
            break
    return samples


# ----------------------------------------------------------------------- scoring


def _failed_or_error(outcome: str | None) -> bool:
    return outcome in ("failed", "error")


def score_candidates(
    candidates: list[Candidate],
    snapshot: RepoSnapshot,
    baseline: SandboxResult | None,
    repro: ReproTest | None,
    sandbox: Sandbox,
    trace: Trace,
    limits: SandboxLimits | None = None,
    deadline: float | None = None,
) -> list[Scorecard]:
    """Score and rank candidates. A sandbox failure affects only the candidate it hit;
    static checks are skipped (and reported as skipped) once ``deadline`` has passed."""
    baseline_outcomes = baseline.results.outcomes if baseline and baseline.results else {}
    cards = []
    for candidate in candidates:
        card = Scorecard(candidate)
        if candidate.visible is None:
            try:
                candidate.visible = run_repo_tests(
                    snapshot, sandbox, overlay=candidate.changed_files, limits=limits
                )
            except SandboxError as exc:
                card.problems.append(f"visible tests not run: {exc}")
        visible = candidate.visible
        outcomes = visible.results.outcomes if visible is not None and visible.completed else {}
        card.visible_all_pass = bool(
            visible is not None and visible.completed and visible.results.all_passed
        )
        card.fixes = sorted(
            t
            for t, o in baseline_outcomes.items()
            if _failed_or_error(o) and outcomes.get(t) == "passed"
        )
        card.regressions = sorted(
            t for t, o in baseline_outcomes.items() if o == "passed" and outcomes.get(t) != "passed"
        )
        if repro is not None and repro.usable:
            try:
                run = run_repo_tests(
                    snapshot,
                    sandbox,
                    overlay=candidate.changed_files,
                    extra_files={repro.path: repro.code},
                    selectors=[repro.path],
                    limits=limits,
                )
            except SandboxError as exc:
                card.problems.append(f"reproduction test not run: {exc}")
            else:
                ok = run.completed and run.results.all_passed
                card.repro = REPRO_VERIFIED if ok else REPRO_FAILED
        if deadline is not None and time.monotonic() > deadline:
            card.lint = CheckResult("ruff", "skipped", detail="time budget exhausted")
            card.types = CheckResult("mypy", "skipped", detail="time budget exhausted")
        else:
            card.lint = lint_delta(snapshot, candidate.changed_files)
            card.types = typecheck_delta(snapshot, candidate.changed_files)
        card.security = security_review(snapshot, candidate.changed_files)
        patch = candidate.attempt.patch
        card.diff_lines = (patch.lines_added + patch.lines_removed) if patch else 0
        trace.add("candidate_scored", **card.to_dict())
        cards.append(card)
    cards.sort(key=lambda c: c.rank_key(), reverse=True)
    for rank, card in enumerate(cards, start=1):
        card.rank = rank
    return cards


def distinct_valid(
    attempts: list[tuple[str, AttemptResult, SandboxResult | None]],
) -> list[Candidate]:
    seen: set[str] = set()
    candidates = []
    for source, attempt, visible in attempts:
        if attempt.status != STATUS_PROPOSED or attempt.patch is None:
            continue
        if attempt.patch.diff in seen:
            continue
        seen.add(attempt.patch.diff)
        candidates.append(Candidate(len(candidates) + 1, source, attempt, visible))
    return candidates
