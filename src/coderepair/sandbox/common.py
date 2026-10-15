"""Pieces shared by the sandbox backends: the sandbox environment and result assembly."""

from __future__ import annotations

import os
from pathlib import Path

from .base import LIMIT_WALL_TIME, SandboxResult
from .process import ProcessOutcome
from .results import ResultsError, read_results_file


def sandbox_env(*, home: str, results_path: str, nonce: str) -> dict[str, str]:
    """The complete environment of a sandboxed run (nothing is inherited from the host)."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": home,
        "TMPDIR": home,
        "USER": "sandbox",
        "LOGNAME": "sandbox",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "NO_COLOR": "1",
        "CODEREPAIR_RESULTS_PATH": results_path,
        "CODEREPAIR_RESULTS_NONCE": nonce,
    }


def finish_result(
    *,
    backend: str,
    isolation: str,
    outcome: ProcessOutcome,
    results_path: Path,
    nonce: str,
    signal_limits: dict[int, str],
    extra_problems: list[str] | None = None,
    limit_override: str | None = None,
) -> SandboxResult:
    limit = limit_override or outcome.limit_exceeded
    rc = outcome.returncode
    if limit is None and rc is not None and rc < 0 and -rc in signal_limits:
        limit = signal_limits[-rc]
    result = SandboxResult(
        backend=backend,
        isolation=isolation,
        exit_code=rc,
        duration_s=outcome.duration_s,
        timed_out=limit == LIMIT_WALL_TIME,
        limit_exceeded=limit,
        stdout=outcome.stdout,
        stderr=outcome.stderr,
        output_truncated=outcome.output_truncated,
        problems=list(extra_problems or []),
    )
    if outcome.stderr.startswith("sandbox-exec:"):
        result.problems.append(f"sandbox failed to start: {outcome.stderr.strip()[:300]}")
    try:
        result.results = read_results_file(results_path, nonce)
    except ResultsError as exc:
        if limit is None:
            result.problems.append(str(exc))
    else:
        if result.results.exitstatus != rc and limit is None:
            result.problems.append(
                f"pytest reported exit status {result.results.exitstatus} "
                f"but the process exited with {rc}"
            )
    return result


MAX_SCRATCH_ENTRIES = 10_000


def scratch_usage(paths: list[Path]) -> tuple[int, int]:
    total, entries = 0, 0
    stack = [str(p) for p in paths]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for entry in it:
                    entries += 1
                    if entries > MAX_SCRATCH_ENTRIES:
                        return total, entries
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_blocks * 512
                    except OSError:
                        continue
        except OSError:
            continue
    return total, entries
