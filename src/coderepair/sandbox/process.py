"""Run a host-side command with bounded output capture, a watchdog and a deadline.

Used by both backends: for Seatbelt the child *is* the sandboxed interpreter;
for Docker it is the ``docker run`` client. The child gets its own session so a
timeout kills its whole process group, and stdout/stderr are drained by
threads that keep only a bounded head and tail.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .base import LIMIT_OUTPUT, LIMIT_WALL_TIME

_CHUNK = 65_536
# Control characters (terminal escape sequences, NUL, ...) from untrusted output are
# replaced before the text is shown to anyone; newlines and tabs are kept.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _printable(text: str) -> str:
    return _CONTROL.sub("\ufffd", text)


class _Capture:
    """Keep the first ``head`` and last ``tail`` bytes of a stream, counting the rest."""

    def __init__(self, keep_bytes: int) -> None:
        self.head_limit = keep_bytes // 4
        self.tail_limit = keep_bytes - self.head_limit
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0

    def feed(self, data: bytes) -> None:
        self.total += len(data)
        room = self.head_limit - len(self.head)
        if room > 0:
            self.head += data[:room]
            data = data[room:]
        if data:
            self.tail += data
            if len(self.tail) > self.tail_limit:
                del self.tail[: len(self.tail) - self.tail_limit]

    @property
    def truncated(self) -> bool:
        return self.total > len(self.head) + len(self.tail)

    def text(self) -> str:
        head = _printable(self.head.decode("utf-8", errors="replace"))
        tail = _printable(self.tail.decode("utf-8", errors="replace"))
        if self.truncated:
            dropped = self.total - len(self.head) - len(self.tail)
            return f"{head}\n[... {dropped} bytes omitted ...]\n{tail}"
        return head + tail


@dataclass
class ProcessOutcome:
    returncode: int | None
    duration_s: float
    stdout: str
    stderr: str
    output_truncated: bool
    limit_exceeded: str | None


def run_monitored(
    argv: list[str],
    *,
    env: dict[str, str],
    cwd: str,
    wall_timeout_s: float,
    keep_output_bytes: int,
    output_hard_cap_bytes: int,
    watchdog: Callable[[int], str | None] | None = None,
    watchdog_interval_s: float = 0.02,
    on_kill: Callable[[], None] | None = None,
) -> ProcessOutcome:
    """Run ``argv``; kill its process group on timeout, output flood or watchdog verdict.

    ``watchdog(pid)`` is polled while the process runs and returns a limit name
    (for example ``"memory"``) when the process must be killed.
    """
    started = time.monotonic()
    proc = subprocess.Popen(  # noqa: S603 - argv is built by the sandbox backend, never a shell
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
    )
    reason: list[str] = []
    lock = threading.Lock()
    reaped = threading.Event()

    def kill(why: str) -> None:
        with lock:
            if not reason:
                reason.append(why)
            # Never signal after the child was reaped: its pid could have been reused.
            if not reaped.is_set():
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        if on_kill is not None:
            on_kill()

    captures = (_Capture(keep_output_bytes), _Capture(keep_output_bytes))

    def drain(stream, capture: _Capture) -> None:
        with stream:
            while chunk := stream.read1(_CHUNK):
                capture.feed(chunk)
                if sum(c.total for c in captures) > output_hard_cap_bytes and not reason:
                    kill(LIMIT_OUTPUT)

    readers = [
        threading.Thread(target=drain, args=(proc.stdout, captures[0]), daemon=True),
        threading.Thread(target=drain, args=(proc.stderr, captures[1]), daemon=True),
    ]
    for reader in readers:
        reader.start()

    deadline = started + wall_timeout_s
    try:
        while proc.poll() is None:
            if time.monotonic() >= deadline:
                kill(LIMIT_WALL_TIME)
                break
            if watchdog is not None and not reason:
                verdict = watchdog(proc.pid)
                if verdict:
                    kill(verdict)
                    break
            time.sleep(watchdog_interval_s)
    finally:
        # Whatever happens here (Ctrl-C, a watchdog error), the child must not outlive us.
        if proc.poll() is None:
            kill(reason[0] if reason else "interrupted")
        with lock:
            returncode = proc.wait()
            reaped.set()
    duration = time.monotonic() - started
    for reader in readers:
        reader.join(timeout=5)
    return ProcessOutcome(
        returncode=returncode,
        duration_s=duration,
        stdout=captures[0].text(),
        stderr=captures[1].text(),
        output_truncated=any(c.truncated for c in captures),
        limit_exceeded=reason[0] if reason else None,
    )
