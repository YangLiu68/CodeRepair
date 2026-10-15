"""Milestone 1 pipeline: issue -> retrieval -> prompt -> proposal -> validated diff.

The pipeline is read-only with respect to the repository: it never writes to
the source tree and never executes repository code or model output. The
result is a diff for a human to review.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Limits
from .execution import describe_result, run_repo_tests
from .issue import ParsedIssue, parse_issue
from .llm.base import BackendError, LLMBackend, LLMRequest, LLMResponse
from .patch import (
    PatchPolicy,
    PatchProposal,
    PatchResult,
    ProposalParseError,
    apply_proposal,
    parse_proposal,
)
from .prompting import PromptBundle, build_prompt
from .repo import RepoSnapshot
from .retrieval import RankedFile, rank_files
from .sandbox.base import Sandbox, SandboxError, SandboxLimits, SandboxResult
from .search import RepoIndex
from .security import scan_for_injection
from .trace import Trace, new_run_id

STATUS_PROPOSED = "proposed"
STATUS_REJECTED = "rejected"
STATUS_NO_EDITS = "no_edits"
STATUS_PARSE_ERROR = "parse_error"
STATUS_BACKEND_ERROR = "backend_error"


@dataclass
class ProposalRun:
    run_id: str
    task_id: str | None
    backend: str
    model: str
    is_mock: bool
    status: str
    issue: ParsedIssue
    retrieval: list[RankedFile]
    prompt: PromptBundle
    snapshot_hash: str
    git_head: str | None
    response: LLMResponse | None = None
    proposal: PatchProposal | None = None
    patch: PatchResult | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    run_dir: Path | None = None
    #: Visible tests run on the patched copy in a sandbox (None if not requested or not run).
    tests: SandboxResult | None = None

    @property
    def diff(self) -> str:
        return self.patch.diff if self.patch and self.patch.ok else ""

    def summary_dict(self) -> dict:
        response = self.response
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "backend": self.backend,
            "model": self.model,
            "is_mock": self.is_mock,
            "status": self.status,
            "summary": self.proposal.summary if self.proposal else "",
            "errors": self.errors,
            "warnings": self.warnings,
            "files_changed": sorted(self.patch.changed_files)
            if self.patch and self.patch.ok
            else [],
            "lines_added": self.patch.lines_added if self.patch else 0,
            "lines_removed": self.patch.lines_removed if self.patch else 0,
            "retrieved_files": [f.path for f in self.prompt.files],
            "input_tokens": response.input_tokens if response else None,
            "output_tokens": response.output_tokens if response else None,
            "usage_is_estimate": response.usage_is_estimate if response else None,
            "llm_latency_s": round(response.latency_s, 3) if response else None,
            "duration_s": round(self.duration_s, 3),
            "snapshot_hash": self.snapshot_hash,
            "git_head": self.git_head,
            "tests": _tests_summary(self.tests),
            "awaiting_human_review": self.status == STATUS_PROPOSED,
        }


def _tests_summary(result: SandboxResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "sandbox": result.backend,
        "isolation": result.isolation,
        "counts": result.results.counts() if result.results else None,
        "failing": [t for t, o in sorted(result.results.outcomes.items()) if o != "passed"]
        if result.results
        else [],
        "limit_exceeded": result.limit_exceeded,
        "problems": result.problems,
        "duration_s": round(result.duration_s, 3),
    }


@dataclass
class RepairContext:
    """Everything derived from the issue and the snapshot before the first model call."""

    issue: ParsedIssue
    index: RepoIndex
    ranked: list[RankedFile]
    bundle: PromptBundle
    warnings: list[str]


def build_context(
    snapshot: RepoSnapshot, issue_text: str, limits: Limits, trace: Trace
) -> RepairContext:
    trace.add(
        "ingest",
        root=str(snapshot.root),
        content_hash=snapshot.content_hash,
        git_head=snapshot.git_head,
        files=snapshot.paths(),
        excluded=[vars(e) for e in snapshot.excluded],
    )
    issue = parse_issue(issue_text)
    trace.add("issue_parsed", issue=issue.to_dict())

    repo_findings = [
        vars(f) for path in snapshot.paths() for f in scan_for_injection(snapshot.text(path), path)
    ]
    trace.add("injection_scan", scope="whole repository", findings=repo_findings)

    index = RepoIndex(snapshot)
    ranked = rank_files(snapshot, index, issue)
    trace.add("retrieval", ranking=[r.to_dict() for r in ranked if r.score > 0][:15])

    bundle = build_prompt(snapshot, index, issue, ranked, limits)
    trace.add(
        "prompt_built", **bundle.to_dict(), system=bundle.request.system, user=bundle.request.user
    )
    warnings = [
        f"possible prompt injection in {finding.source} line {finding.line} "
        f"({finding.rule}, {finding.severity}): {finding.excerpt!r}"
        for finding in bundle.injection_findings
    ]
    warnings += [
        f"redacted {redaction['count']} {redaction['kind']} secret(s) "
        f"from {redaction['source']} before sending"
        for redaction in bundle.redactions
    ]
    return RepairContext(issue, index, ranked, bundle, warnings)


@dataclass
class AttemptResult:
    """One model call and the static validation of what it returned."""

    status: str
    response: LLMResponse | None = None
    proposal: PatchProposal | None = None
    patch: PatchResult | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    backend_error: BackendError | None = None


def attempt_proposal(
    request: LLMRequest,
    backend: LLMBackend,
    snapshot: RepoSnapshot,
    policy: PatchPolicy,
    trace: Trace,
) -> AttemptResult:
    try:
        response = backend.complete(request)
    except BackendError as exc:
        trace.add("llm_error", error=str(exc), retryable=exc.retryable)
        return AttemptResult(
            STATUS_BACKEND_ERROR, errors=[f"backend error: {exc}"], backend_error=exc
        )
    trace.add(
        "llm_response",
        model=response.model,
        text=response.text,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        usage_is_estimate=response.usage_is_estimate,
        latency_s=round(response.latency_s, 3),
        stop_reason=response.stop_reason,
        request_id=response.request_id,
        metadata=response.metadata,
    )
    attempt = AttemptResult(STATUS_PARSE_ERROR, response=response)
    try:
        proposal = parse_proposal(response.text)
    except ProposalParseError as exc:
        attempt.errors.append(f"could not parse proposal: {exc}")
        trace.add("parse_error", error=str(exc))
        return attempt
    attempt.proposal = proposal
    trace.add("proposal_parsed", proposal=proposal.model_dump())
    if not proposal.edits:
        attempt.status = STATUS_NO_EDITS
        attempt.errors.append("model proposed no edits")
        return attempt
    result = apply_proposal(snapshot, proposal, policy)
    attempt.patch = result
    trace.add("patch_validated", **result.to_dict(), diff=result.diff)
    attempt.warnings.extend(result.warnings)
    if result.ok:
        attempt.status = STATUS_PROPOSED
    else:
        attempt.status = STATUS_REJECTED
        attempt.errors.extend(result.errors)
    return attempt


def propose_patch(
    snapshot: RepoSnapshot,
    issue_text: str,
    backend: LLMBackend,
    *,
    limits: Limits | None = None,
    policy: PatchPolicy | None = None,
    runs_dir: Path | None = None,
    task_id: str | None = None,
    sandbox: Sandbox | None = None,
    sandbox_limits: SandboxLimits | None = None,
) -> ProposalRun:
    """Propose a patch for ``issue_text`` with a single model call.

    With ``sandbox``, also run the repository's visible tests on a patched
    throwaway copy (the repository itself is never changed).
    """
    limits = limits or Limits()
    policy = policy or PatchPolicy.from_limits(limits)
    started = time.monotonic()
    run_id = new_run_id(task_id or snapshot.root.name)
    trace = Trace(run_id)
    trace.add(
        "start",
        task_id=task_id,
        backend=backend.name,
        model=backend.model,
        is_mock=backend.is_mock,
    )
    context = build_context(snapshot, issue_text, limits, trace)
    run = ProposalRun(
        run_id=run_id,
        task_id=task_id,
        backend=backend.name,
        model=backend.model,
        is_mock=backend.is_mock,
        status=STATUS_BACKEND_ERROR,
        issue=context.issue,
        retrieval=context.ranked,
        prompt=context.bundle,
        snapshot_hash=snapshot.content_hash,
        git_head=snapshot.git_head,
        warnings=list(context.warnings),
    )
    attempt = attempt_proposal(context.bundle.request, backend, snapshot, policy, trace)
    run.status = attempt.status
    run.response = attempt.response
    run.proposal = attempt.proposal
    run.patch = attempt.patch
    run.errors.extend(attempt.errors)
    run.warnings.extend(attempt.warnings)
    if sandbox is not None and run.status == STATUS_PROPOSED and run.patch is not None:
        _run_visible_tests(run, snapshot, sandbox, sandbox_limits, trace)

    run.duration_s = time.monotonic() - started
    trace.add("result", **run.summary_dict())
    if runs_dir is not None:
        run.run_dir = _write_artifacts(run, trace, runs_dir)
    return run


def _run_visible_tests(
    run: ProposalRun,
    snapshot: RepoSnapshot,
    sandbox: Sandbox,
    limits: SandboxLimits | None,
    trace: Trace,
) -> None:
    trace.add("sandbox_start", sandbox=sandbox.name, isolation=sandbox.isolation)
    try:
        result = run_repo_tests(snapshot, sandbox, overlay=run.patch.changed_files, limits=limits)
    except SandboxError as exc:
        run.warnings.append(f"tests not run: {exc}")
        trace.add("sandbox_error", error=str(exc))
        return
    run.tests = result
    trace.add("sandbox_tests", **result.to_dict(), summary=describe_result(result))


def _write_artifacts(run: ProposalRun, trace: Trace, runs_dir: Path) -> Path:
    run_dir = runs_dir / run.run_id
    run_dir.mkdir(parents=True, mode=0o700)
    trace.write_jsonl(run_dir / "trace.jsonl")
    (run_dir / "summary.json").write_text(
        json.dumps(run.summary_dict(), indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "prompt.txt").write_text(
        f"=== SYSTEM ===\n{run.prompt.request.system}\n=== USER ===\n{run.prompt.request.user}\n",
        encoding="utf-8",
    )
    if run.proposal is not None:
        (run_dir / "proposal.json").write_text(
            run.proposal.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    if run.diff:
        (run_dir / "proposal.patch").write_text(run.diff, encoding="utf-8")
    return run_dir
