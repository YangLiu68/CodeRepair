"""Escape and abuse probes: hostile test suites that every sandbox backend must contain.

Each probe is a small pytest module that attempts one class of attack. It runs
in its own sandbox session, and containment is judged on the host, not only
by the probe's own assertions:

* a canary secret file outside the workspace must not appear in any output,
  and its directory must be unchanged;
* a TCP listener on the host loopback must receive no connection;
* a sentinel process owned by the host must still be alive;
* the workspace must be unchanged and no process may outlive the session;
* a host environment variable set during the run must not be visible.

``coderepair sandbox selftest`` runs them; ``tests/test_sandbox.py`` runs them
for every backend available on the machine.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..config import PROJECT_ROOT
from .base import (
    LIMIT_CPU_TIME,
    LIMIT_DISK,
    LIMIT_FILE_SIZE,
    LIMIT_MEMORY,
    LIMIT_OUTPUT,
    LIMIT_WALL_TIME,
    Sandbox,
    SandboxJob,
    SandboxLimits,
    SandboxResult,
)
from .workspace import new_run_dir

BLOCKED = "blocked"  # the session completes and every attempt inside it failed
NO_RESULTS = "no-results"  # the harness must refuse the session's results

_HEADER = '''\
import json
import os
import pathlib
import socket
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = json.loads(ROOT.joinpath("probe_config.json").read_text())


def leak(value):
    """An attempt succeeded: show what it obtained (so the host-side canary check sees it
    in the failure report) and fail the test."""
    print("LEAKED:", value)
    raise AssertionError("attack succeeded")
'''


@dataclass(frozen=True)
class Probe:
    name: str
    threat: str
    code: str
    expect: frozenset[str]
    limits: SandboxLimits = field(default_factory=SandboxLimits)


def _p(name: str, threat: str, body: str, expect: set[str], **limits) -> Probe:
    code = _HEADER + "\n\n" + textwrap.dedent(body).strip() + "\n"
    base = SandboxLimits(wall_timeout_s=30.0)
    return Probe(name, threat, code, frozenset(expect), replace(base, **limits))


PROBES: tuple[Probe, ...] = (
    _p(
        "network",
        "exfiltrate over TCP, loopback, DNS or a container-runtime socket",
        """
        def test_external_tcp():
            with pytest.raises(OSError):
                leak(socket.create_connection(("1.1.1.1", 53), timeout=3))

        def test_host_loopback_listener():
            with pytest.raises(OSError):
                leak(socket.create_connection(("127.0.0.1", CFG["port"]), timeout=3))

        def test_dns():
            with pytest.raises(OSError):
                leak(socket.getaddrinfo("example.com", 443))

        @pytest.mark.parametrize("path", CFG["runtime_sockets"])
        def test_container_runtime_socket(path):
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            with pytest.raises(OSError):
                s.connect(path)
                leak(path)
        """,
        {BLOCKED},
    ),
    _p(
        "host-files",
        "read secrets, the home directory or benchmark solutions",
        """
        def test_read_canary_secret():
            with pytest.raises(OSError):
                leak(open(CFG["canary_file"]).read())

        def test_stat_canary_secret():
            with pytest.raises(OSError):
                leak(os.stat(CFG["canary_file"]))

        def test_list_home():
            with pytest.raises(OSError):
                leak(os.listdir(CFG["home"]))

        def test_list_ssh_dir():
            with pytest.raises(OSError):
                leak(os.listdir(os.path.join(CFG["home"], ".ssh")))

        def test_read_benchmark_solution():
            with pytest.raises(OSError):
                leak(open(CFG["solution_file"]).read())

        def test_symlink_to_secret():
            link = os.path.join(os.environ["TMPDIR"], "link")
            with pytest.raises(OSError):
                os.symlink(CFG["canary_file"], link)
                leak(open(link).read())
        """,
        {BLOCKED},
    ),
    _p(
        "host-writes",
        "write outside the scratch area or modify the repository",
        """
        def test_write_canary_dir():
            with pytest.raises(OSError):
                open(os.path.join(CFG["canary_dir"], "pwned.txt"), "w").write("x")

        def test_create_file_in_workspace():
            with pytest.raises(OSError):
                open("pwned.txt", "w").write("x")

        def test_modify_repository_file():
            with pytest.raises(OSError):
                open("probe_config.json", "a").write("x")

        def test_scratch_space_is_writable():
            path = os.path.join(os.environ["TMPDIR"], "ok.txt")
            with open(path, "w") as fh:
                fh.write("ok")
            assert open(path).read() == "ok"
        """,
        {BLOCKED},
    ),
    _p(
        "environment",
        "read credentials from inherited environment variables",
        """
        def test_host_variable_absent():
            assert CFG["env_name"] not in os.environ
            for value in os.environ.values():
                assert CFG["canary"] not in value
        """,
        {BLOCKED},
    ),
    _p(
        "processes",
        "signal host processes or spawn a fork bomb",
        """
        import signal

        def test_signal_host_process():
            with pytest.raises(OSError):
                os.kill(CFG["sentinel_pid"], signal.SIGTERM)

        def test_process_count_is_capped():
            started = []
            for _ in range(500):
                try:
                    started.append(subprocess.Popen(
                        [sys.executable, "-c", "import time; time.sleep(60)"],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL))
                except OSError:
                    break
            assert len(started) < CFG["max_processes"]
        """,
        {BLOCKED},
    ),
    _p(
        "process-info",
        "read another process's arguments and environment (API keys of the harness or a shell)",
        """
        import ctypes


        def _arguments_and_environment(pid):
            if sys.platform == "darwin":
                libc = ctypes.CDLL(None, use_errno=True)
                mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2
                size = ctypes.c_size_t(1 << 18)
                buf = ctypes.create_string_buffer(1 << 18)
                if libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0:
                    raise OSError(ctypes.get_errno(), "sysctl refused")
                return buf.raw[: size.value]
            with open(f"/proc/{pid}/environ", "rb") as fh:
                return fh.read() + open(f"/proc/{pid}/cmdline", "rb").read()


        @pytest.mark.parametrize("who", ["sentinel", "parent"])
        def test_other_process(who):
            pid = CFG["sentinel_pid"] if who == "sentinel" else os.getppid()
            try:
                data = _arguments_and_environment(pid)
            except OSError:
                return
            assert CFG["canary"].encode() not in data, data
        """,
        {BLOCKED},
    ),
    _p(
        "results-fifo",
        "replace the results file with a named pipe so the harness blocks reading it",
        """
        def test_plant_fifo():
            os.mkfifo(os.environ["CODEREPAIR_RESULTS_PATH"])
            os._exit(0)
        """,
        {NO_RESULTS},
    ),
    _p(
        "memory-bomb",
        "exhaust host memory",
        """
        def test_allocate_until_killed():
            chunks = []
            for _ in range(256):
                chunks.append(b"\\x01" * (32 * 1024 * 1024))
        """,
        {LIMIT_MEMORY},
        memory_mb=256,
    ),
    _p(
        "cpu-spin",
        "burn CPU forever",
        """
        def test_spin():
            while True:
                pass
        """,
        {LIMIT_CPU_TIME},
        cpu_seconds=2,
        wall_timeout_s=30.0,
    ),
    _p(
        "sleep-forever",
        "hang without using CPU so CPU limits never fire",
        """
        import time

        def test_sleep():
            time.sleep(10**6)
        """,
        {LIMIT_WALL_TIME},
        wall_timeout_s=3.0,
    ),
    _p(
        "output-flood",
        "flood the harness with output",
        """
        def test_flood(capsys):
            with capsys.disabled():
                while True:
                    sys.stdout.write("x" * 1_000_000)
        """,
        {LIMIT_OUTPUT},
    ),
    _p(
        "disk-fill",
        "fill the disk through the scratch area",
        """
        def test_fill_scratch():
            written = 0
            try:
                for i in range(2000):
                    with open(os.path.join(os.environ["TMPDIR"], f"f{i}"), "wb") as fh:
                        fh.write(b"\\0" * (1024 * 1024))
                    written += 1
            except OSError:
                pass
            assert written <= CFG["tmp_mb"] + 4
        """,
        {LIMIT_DISK, BLOCKED},
        tmp_mb=32,
    ),
    _p(
        "file-size",
        "write one huge file",
        """
        def test_big_file():
            path = os.path.join(os.environ["TMPDIR"], "big")
            with pytest.raises(OSError):
                with open(path, "wb") as fh:
                    for _ in range(64):
                        fh.write(b"\\0" * (1024 * 1024))
                        fh.flush()
        """,
        {BLOCKED, LIMIT_FILE_SIZE, LIMIT_DISK},
        max_file_mb=8,
        tmp_mb=48,
    ),
    _p(
        "early-exit",
        "exit with status 0 before pytest reports failures",
        """
        def test_exit_before_reporting():
            os._exit(0)

        def test_would_fail():
            assert False
        """,
        {NO_RESULTS},
    ),
    _p(
        "forged-results",
        "overwrite the results file with a fake all-pass report",
        """
        def test_forge():
            fake = {"nonce": "guess", "tests": {"tests/test_probe.py::test_forge": "passed"},
                    "collect_errors": [], "exitstatus": 0}
            with open(os.environ["CODEREPAIR_RESULTS_PATH"], "w") as fh:
                json.dump(fake, fh)
            os._exit(0)
        """,
        {NO_RESULTS},
    ),
)


@dataclass
class ProbeReport:
    name: str
    threat: str
    expected: list[str]
    observed: str
    contained: bool
    duration_s: float
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "threat": self.threat,
            "expected": self.expected,
            "observed": self.observed,
            "contained": self.contained,
            "duration_s": round(self.duration_s, 2),
            "details": self.details,
        }


def _observed(result: SandboxResult) -> str:
    if result.limit_exceeded:
        return result.limit_exceeded
    if result.results is None:
        return NO_RESULTS
    if result.problems:
        return "rejected: " + result.problems[0][:120]
    if result.results.all_passed:
        return BLOCKED
    failing = [t for t, o in result.results.outcomes.items() if o != "passed"]
    return "attempt-succeeded: " + ", ".join(sorted(failing)[:5])


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(str(path.relative_to(root)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _runtime_sockets(home: str) -> list[str]:
    return [
        "/var/run/docker.sock",
        os.path.join(home, ".docker", "run", "docker.sock"),
        os.path.join(home, ".colima", "default", "docker.sock"),
    ]


def run_probe(sandbox: Sandbox, probe: Probe) -> ProbeReport:
    canary = f"CANARY-{secrets.token_hex(12)}"
    env_name = f"CODEREPAIR_PROBE_SECRET_{secrets.token_hex(4).upper()}"
    canary_dir = Path(os.path.realpath(tempfile.mkdtemp(prefix="coderepair-canary-")))
    (canary_dir / "secret.txt").write_text(canary, encoding="utf-8")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.setblocking(False)
    # A host process holding the canary in its arguments and environment, like a shell
    # with an API key exported.
    sentinel = subprocess.Popen(  # noqa: S603 - fixed argv
        [sys.executable, "-c", "import time; time.sleep(600)", canary],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", env_name: canary},
    )
    home = os.path.realpath(Path.home())
    solution = PROJECT_ROOT / "benchmarks" / "tasks" / "t01_paginate_off_by_one" / "solution.json"
    config = {
        "canary_file": str(canary_dir / "secret.txt"),
        "canary_dir": str(canary_dir),
        "canary": canary,
        "env_name": env_name,
        "home": home,
        "port": listener.getsockname()[1],
        "runtime_sockets": _runtime_sockets(home),
        "sentinel_pid": sentinel.pid,
        "solution_file": str(solution if solution.exists() else canary_dir / "secret.txt"),
        "max_processes": probe.limits.max_processes,
        "tmp_mb": probe.limits.tmp_mb,
    }
    run_dir = new_run_dir(prefix="coderepair-probe-")
    (run_dir.workspace / "probe_config.json").write_text(json.dumps(config), encoding="utf-8")
    (run_dir.workspace / "tests").mkdir()
    (run_dir.workspace / "tests" / "test_probe.py").write_text(probe.code, encoding="utf-8")
    before = _tree_digest(run_dir.workspace)
    os.environ[env_name] = canary
    try:
        result = sandbox.run(SandboxJob(run_dir.workspace, limits=probe.limits))
    finally:
        os.environ.pop(env_name, None)
    details: list[str] = []
    try:
        observed = _observed(result)
        if observed not in probe.expect:
            details.append(f"expected {sorted(probe.expect)}, observed {observed}")
        if probe.expect == {NO_RESULTS} and result.results is not None:
            details.append("harness accepted results from a session that should be rejected")
        leaked_in = [
            name
            for name, text in (("stdout", result.stdout), ("stderr", result.stderr))
            if canary in text
        ]
        for scratch in (run_dir.tmp, run_dir.out):
            for path in scratch.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    with path.open("rb") as fh:
                        if canary.encode() in fh.read(4_000_000):
                            leaked_in.append(str(path.relative_to(run_dir.root)))
        if leaked_in:
            details.append(f"canary secret leaked into {leaked_in}")
        if sorted(p.name for p in canary_dir.iterdir()) != ["secret.txt"]:
            details.append("canary directory was modified")
        try:
            conn, _ = listener.accept()
        except BlockingIOError:
            pass
        else:
            conn.close()
            details.append("host loopback listener received a connection")
        if sentinel.poll() is not None:
            details.append("host sentinel process was killed")
        if _tree_digest(run_dir.workspace) != before:
            details.append("workspace was modified")
        if result.duration_s > probe.limits.wall_timeout_s + 10:
            details.append(f"run took {result.duration_s:.1f}s, beyond its wall-clock limit")
    finally:
        listener.close()
        sentinel.kill()
        sentinel.wait()
        shutil.rmtree(canary_dir, ignore_errors=True)
        run_dir.cleanup()
    return ProbeReport(
        name=probe.name,
        threat=probe.threat,
        expected=sorted(probe.expect),
        observed=observed,
        contained=not details,
        duration_s=result.duration_s,
        details=details,
    )


def run_probes(sandbox: Sandbox, names: list[str] | None = None) -> list[ProbeReport]:
    selected = [p for p in PROBES if names is None or p.name in names]
    return [run_probe(sandbox, probe) for probe in selected]
