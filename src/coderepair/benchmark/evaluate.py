"""Harness-side evaluation of a candidate patch against a task's hidden tests.

A patch *resolves* a task when, with the hidden tests added, every
fail-to-pass test passes and every pass-to-pass test still passes. A test that
is not reported counts as failed, so a patch cannot score by breaking
collection or deleting behaviour. Everything runs in a sandbox; the hidden
tests never reach the agent.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..execution import run_repo_tests
from ..repo import ingest_repository
from ..sandbox.base import Sandbox, SandboxLimits, SandboxResult
from .tasks import TaskSpec

STATUS_RESOLVED = "resolved"
STATUS_UNRESOLVED = "unresolved"


@dataclass
class PatchEvaluation:
    task_id: str
    status: str
    fail_to_pass: dict[str, str] = field(default_factory=dict)
    pass_to_pass_broken: dict[str, str] = field(default_factory=dict)
    reason: str = ""
    sandbox: SandboxResult | None = None

    @property
    def resolved(self) -> bool:
        return self.status == STATUS_RESOLVED

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "reason": self.reason,
            "fail_to_pass": self.fail_to_pass,
            "pass_to_pass_broken": self.pass_to_pass_broken,
            "sandbox": self.sandbox.to_dict() if self.sandbox else None,
        }


def evaluate_patch(
    task: TaskSpec,
    overlay: Mapping[str, str],
    sandbox: Sandbox,
    *,
    limits: SandboxLimits | None = None,
) -> PatchEvaluation:
    """Run the task's visible and hidden tests on the patched repository in ``sandbox``."""
    snapshot = ingest_repository(task.repo_dir, (task.dir,))
    result = run_repo_tests(
        snapshot,
        sandbox,
        overlay=overlay,
        extra_files=task.hidden_test_overlay(),
        limits=limits,
    )
    return judge(task, result)


def judge(task: TaskSpec, result: SandboxResult) -> PatchEvaluation:
    evaluation = PatchEvaluation(task.id, STATUS_UNRESOLVED, sandbox=result)
    if result.limit_exceeded:
        evaluation.reason = f"test session stopped: {result.limit_exceeded} limit exceeded"
        return evaluation
    if result.results is None or result.problems:
        evaluation.reason = "no trustworthy test results: " + "; ".join(result.problems)
        return evaluation
    outcomes = result.results.outcomes
    evaluation.fail_to_pass = {t: outcomes.get(t, "missing") for t in task.fail_to_pass}
    evaluation.pass_to_pass_broken = {
        t: outcomes.get(t, "missing") for t in task.pass_to_pass if outcomes.get(t) != "passed"
    }
    still_failing = [t for t, o in evaluation.fail_to_pass.items() if o != "passed"]
    if still_failing:
        evaluation.reason = (
            f"{len(still_failing)}/{len(task.fail_to_pass)} fail-to-pass tests not passing"
        )
    elif evaluation.pass_to_pass_broken:
        evaluation.reason = f"{len(evaluation.pass_to_pass_broken)} previously passing tests broken"
    elif result.results.collect_errors:
        evaluation.reason = f"collection errors: {list(result.results.collect_errors)[:3]}"
    else:
        evaluation.status = STATUS_RESOLVED
        evaluation.reason = "all fail-to-pass and pass-to-pass tests pass"
    return evaluation
