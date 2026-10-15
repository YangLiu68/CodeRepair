"""Run a repository's tests inside a sandbox, optionally with a candidate patch applied.

This is the only path by which repository code or model-written code is
executed. The repository on disk is never modified: a throwaway workspace is
written from the in-memory snapshot plus the patch overlay, handed to the
sandbox, and deleted afterwards.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .repo import RepoSnapshot
from .sandbox.base import Sandbox, SandboxJob, SandboxLimits, SandboxResult
from .sandbox.workspace import prepare_run_dir


def run_repo_tests(
    snapshot: RepoSnapshot,
    sandbox: Sandbox,
    *,
    overlay: Mapping[str, str] | None = None,
    extra_files: Mapping[str, str] | None = None,
    selectors: Sequence[str] = (),
    limits: SandboxLimits | None = None,
) -> SandboxResult:
    with prepare_run_dir(snapshot, overlay=overlay, extra_files=extra_files) as run_dir:
        job = SandboxJob(
            run_dir.workspace, selectors=tuple(selectors), limits=limits or SandboxLimits()
        )
        return sandbox.run(job)


def describe_result(result: SandboxResult, *, max_failures: int = 8) -> str:
    """A short human-readable summary of a sandboxed test session."""
    if result.limit_exceeded:
        head = f"stopped: {result.limit_exceeded} limit exceeded after {result.duration_s:.1f}s"
    elif result.results is None:
        head = "no usable test results: " + "; ".join(result.problems or ["unknown error"])
    else:
        counts = result.results.counts()
        head = ", ".join(f"{n} {k}" for k, n in counts.items() if n) or "no tests collected"
        if result.results.collect_errors:
            head += f"; collection errors in {', '.join(result.results.collect_errors[:5])}"
        if result.problems:
            head += "; " + "; ".join(result.problems)
    lines = [f"{head} [{result.backend}]"]
    if result.results is not None:
        bad = [(t, o) for t, o in sorted(result.results.outcomes.items()) if o != "passed"]
        for test_id, outcome in bad[:max_failures]:
            lines.append(f"  {outcome.upper():<7} {test_id}")
        if len(bad) > max_failures:
            lines.append(f"  ... and {len(bad) - max_failures} more")
    return "\n".join(lines)
