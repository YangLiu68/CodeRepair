"""Sandbox interface shared by the container and the macOS Seatbelt backends.

Repository code and model-written patches are only ever executed through a
:class:`Sandbox`. A sandbox runs one fixed command (pytest through the runner
bundle) on a prepared workspace and must provide:

* no network access (including loopback and DNS),
* no access to the host's home directory, credentials, project files or
  container runtime socket,
* a read-only workspace plus a small writable scratch area,
* a scrubbed environment (no host variables),
* wall-clock, CPU, memory, disk and output limits,
* no process that outlives the run.

What comes back (exit code, output, the per-test results file) is untrusted.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .results import TestResults

RESULTS_FILE = "results.json"

# Signals that a run ended because a limit was hit, by backend-independent name.
LIMIT_WALL_TIME = "wall-time"
LIMIT_CPU_TIME = "cpu-time"
LIMIT_MEMORY = "memory"
LIMIT_DISK = "disk"
LIMIT_FILE_SIZE = "file-size"
LIMIT_OUTPUT = "output"

_TEST_SELECTOR_RE = re.compile(r"^[A-Za-z0-9_./\-]+(?:::[^\x00-\x1f]+)?$")


class SandboxError(RuntimeError):
    """The sandbox could not be prepared or started (not a test failure)."""


class SandboxUnavailable(SandboxError):
    """No usable sandbox backend; untrusted code will not be run."""


@dataclass(frozen=True)
class SandboxLimits:
    wall_timeout_s: float = 60.0
    cpu_seconds: int = 60
    memory_mb: int = 512
    tmp_mb: int = 64
    #: Seatbelt: cap on bytes the process writes to disk in total, which also counts
    #: files that were deleted while open (invisible to a directory scan).
    disk_write_mb: int = 256
    max_file_mb: int = 32
    max_open_files: int = 256
    max_processes: int = 64  # container backend; Seatbelt forbids fork() entirely
    output_bytes: int = 65_536  # kept per stream (head + tail)
    output_hard_cap_bytes: int = 8_000_000  # the run is killed beyond this


@dataclass(frozen=True)
class SandboxJob:
    """One sandboxed pytest run.

    ``workspace`` is a directory the harness prepared (see ``workspace.py``);
    the sandbox mounts or exposes it read-only. ``selectors`` optionally
    restrict the run to some test files or node ids.
    """

    workspace: Path
    selectors: tuple[str, ...] = ()
    limits: SandboxLimits = field(default_factory=SandboxLimits)
    nonce: str = field(default_factory=lambda: secrets.token_hex(16))

    def pytest_args(self) -> list[str]:
        for selector in self.selectors:
            if selector.startswith("-") or not _TEST_SELECTOR_RE.match(selector):
                raise SandboxError(f"invalid test selector {selector!r}")
            if ".." in selector.split("::", 1)[0].split("/"):
                raise SandboxError(f"test selector escapes the workspace: {selector!r}")
        return [
            "-p",
            "coderepair_results",
            "-p",
            "no:cacheprovider",
            "-q",
            "--color=no",
            "-o",
            "console_output_style=classic",
            *self.selectors,
        ]


@dataclass
class SandboxResult:
    backend: str
    isolation: str
    exit_code: int | None
    duration_s: float
    timed_out: bool = False
    limit_exceeded: str | None = None
    stdout: str = ""
    stderr: str = ""
    output_truncated: bool = False
    results: TestResults | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def completed(self) -> bool:
        """The test session ran to the end and reported trustworthy-looking results."""
        return self.results is not None and not self.problems and self.limit_exceeded is None

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "isolation": self.isolation,
            "exit_code": self.exit_code,
            "duration_s": round(self.duration_s, 3),
            "timed_out": self.timed_out,
            "limit_exceeded": self.limit_exceeded,
            "output_truncated": self.output_truncated,
            "problems": self.problems,
            "results": self.results.to_dict() if self.results else None,
            "stdout_tail": self.stdout[-4000:],
            "stderr_tail": self.stderr[-2000:],
        }


class Sandbox(Protocol):
    name: str
    #: One-line description of the isolation boundary, shown to users and in traces.
    isolation: str

    def available(self) -> tuple[bool, str]: ...

    def run(self, job: SandboxJob) -> SandboxResult: ...
