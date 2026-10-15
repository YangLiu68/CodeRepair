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
from .issue import ParsedIssue, parse_issue
from .llm.base import BackendError, LLMBackend, LLMResponse
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
            "awaiting_human_review": self.status == STATUS_PROPOSED,
        }


def propose_patch(
    snapshot: RepoSnapshot,
    issue_text: str,
    backend: LLMBackend,
    *,
    limits: Limits | None = None,
    policy: PatchPolicy | None = None,
    runs_dir: Path | None = None,
    task_id: str | None = None,
) -> ProposalRun:
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

    run = ProposalRun(
        run_id=run_id,
        task_id=task_id,
        backend=backend.name,
        model=backend.model,
        is_mock=backend.is_mock,
        status=STATUS_BACKEND_ERROR,
        issue=issue,
        retrieval=ranked,
        prompt=bundle,
        snapshot_hash=snapshot.content_hash,
        git_head=snapshot.git_head,
    )
    for finding in bundle.injection_findings:
        run.warnings.append(
            f"possible prompt injection in {finding.source} line {finding.line} "
            f"({finding.rule}, {finding.severity}): {finding.excerpt!r}"
        )
    for redaction in bundle.redactions:
        run.warnings.append(
            f"redacted {redaction['count']} {redaction['kind']} secret(s) "
            f"from {redaction['source']} before sending"
        )

    try:
        response = backend.complete(bundle.request)
    except BackendError as exc:
        run.errors.append(f"backend error: {exc}")
        trace.add("llm_error", error=str(exc), retryable=exc.retryable)
    else:
        run.response = response
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
        _evaluate_response(run, snapshot, response.text, policy, trace)

    run.duration_s = time.monotonic() - started
    trace.add("result", **run.summary_dict())
    if runs_dir is not None:
        run.run_dir = _write_artifacts(run, trace, runs_dir)
    return run


def _evaluate_response(
    run: ProposalRun, snapshot: RepoSnapshot, text: str, policy: PatchPolicy, trace: Trace
) -> None:
    try:
        proposal = parse_proposal(text)
    except ProposalParseError as exc:
        run.status = STATUS_PARSE_ERROR
        run.errors.append(f"could not parse proposal: {exc}")
        trace.add("parse_error", error=str(exc))
        return
    run.proposal = proposal
    trace.add("proposal_parsed", proposal=proposal.model_dump())
    if not proposal.edits:
        run.status = STATUS_NO_EDITS
        run.errors.append("model proposed no edits")
        return
    result = apply_proposal(snapshot, proposal, policy)
    run.patch = result
    trace.add("patch_validated", **result.to_dict(), diff=result.diff)
    run.warnings.extend(result.warnings)
    if result.ok:
        run.status = STATUS_PROPOSED
    else:
        run.status = STATUS_REJECTED
        run.errors.extend(result.errors)


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
