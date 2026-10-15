"""macOS Seatbelt backend: ``sandbox-exec`` with a deny-by-default profile.

This is the local fallback for machines without a container runtime. It runs
on the host kernel, so it is weaker than a container (a kernel or Seatbelt bug
is a host compromise), and ``sandbox-exec`` is deprecated by Apple although it
still ships and underpins other developer sandboxes. Results are labelled with
this backend's ``isolation`` string everywhere they are shown.

Guarantees, each covered by an abuse probe (``probes.py``):

* the profile denies everything not listed: no network (including loopback,
  DNS and Unix sockets), no ``fork``/``exec`` beyond the interpreter itself,
  no signals to other processes, no IPC or Mach services;
* reads are limited to the OS, the Python installation's ``lib``, the runner
  bundle and this run's directory; file metadata outside them is hidden;
* writes are limited to the run's scratch and output directories;
* the environment is replaced, not filtered;
* CPU time, file size and open files are capped with ``setrlimit``; macOS
  ignores memory rlimits, so a watchdog polls the process's physical
  footprint and its scratch-space usage and kills it past the limit (it can
  overshoot by what the process allocates within one poll interval).
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import sys
from pathlib import Path

from .base import (
    LIMIT_CPU_TIME,
    LIMIT_DISK,
    LIMIT_FILE_SIZE,
    LIMIT_MEMORY,
    RESULTS_FILE,
    SandboxError,
    SandboxJob,
    SandboxLimits,
    SandboxResult,
)
from .common import MAX_SCRATCH_ENTRIES, finish_result, sandbox_env, scratch_usage
from .process import run_monitored

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
ISOLATION = (
    "macOS Seatbelt (sandbox-exec), process-level on the host kernel: no network, no fork/exec, "
    "reads limited to OS + Python + workspace, writes limited to a scratch dir; weaker than a "
    "container"
)
_SYSTEM_READ_PATHS = ("/System", "/usr/lib", "/private/var/db/dyld")
_DEVICE_READ = ("/dev/null", "/dev/zero", "/dev/random", "/dev/urandom")
_SYSCTL_NAMES = (
    "hw.ncpu",
    "hw.activecpu",
    "hw.logicalcpu",
    "hw.logicalcpu_max",
    "hw.physicalcpu",
    "hw.physicalcpu_max",
    "hw.memsize",
    "hw.pagesize",
    "hw.cachelinesize",
    "hw.machine",
    "kern.ostype",
    "kern.hostname",  # os.uname()
    "kern.version",  # os.uname()
    "kern.osrelease",
    "kern.osversion",
    "kern.osproductversion",
    "sysctl.proc_translated",
)
_DISK_CHECK_EVERY = 2  # watchdog ticks (20 ms each) between scratch-space scans

# rlimits are set by a tiny launcher just before exec'ing sandbox-exec (no preexec_fn,
# which is unsafe in threaded programs). argv: limits-json, then the command.
_LAUNCHER = (
    "import json, os, resource, sys\n"
    "for name, value in json.loads(sys.argv[1]).items():\n"
    "    resource.setrlimit(getattr(resource, name), (value, value))\n"
    "os.execv(sys.argv[2], sys.argv[2:])\n"
)


def _sbpl_path(path: str | Path) -> str:
    text = str(path)
    if not text.startswith("/") or any(c in text for c in '"\\') or any(ord(c) < 32 for c in text):
        raise SandboxError(f"path cannot be used in a Seatbelt profile: {text!r}")
    return f'"{text}"'


def python_runtime() -> tuple[Path, list[Path], list[Path]]:
    """The interpreter to run, the paths it must read, and extra executables it execs."""
    base_exe = Path(os.path.realpath(getattr(sys, "_base_executable", sys.executable)))
    prefix = Path(os.path.realpath(sys.base_prefix))
    # Only the standard library and shared libraries under <prefix>/lib, never the whole
    # installation prefix (which may be /usr/local or a home directory).
    reads = [base_exe, prefix / "lib"]
    execs = [base_exe]
    if prefix.parent.parent.name == "Python.framework":
        # Framework builds: the interpreter re-executes Python.app and links the
        # framework's own Python dylib.
        app = prefix / "Resources" / "Python.app" / "Contents" / "MacOS" / "Python"
        reads += [prefix / "Python", prefix / "Resources"]
        if app.exists():
            execs.append(app)
    return base_exe, reads, execs


def build_profile(
    *, read_paths: list[Path], write_paths: list[Path], exec_paths: list[Path]
) -> str:
    """Render the Seatbelt profile. Every path must be absolute and already resolved."""
    allowed = [*_SYSTEM_READ_PATHS, *map(str, read_paths), *map(str, write_paths)]
    ancestors = sorted({str(a) for p in allowed for a in Path(p).parents} | {"/"})
    lines = [
        "(version 1)",
        "(deny default)",
        ";; the interpreter may start; nothing else may be executed or forked",
        "(allow process-exec " + " ".join(f"(literal {_sbpl_path(p)})" for p in exec_paths) + ")",
        "(allow signal (target self))",
        ";; process-info is not covered by (deny default) on macOS 15: without this rule",
        ";; KERN_PROCARGS2 / proc_pidinfo reveal any same-user process's arguments and",
        ";; environment (API keys in the parent's environment, for example)",
        "(deny process-info*)",
        ";; ...but a process may inspect itself (libinfo does, e.g. inside getaddrinfo)",
        "(allow process-info* (target self))",
        ";; only harmless hardware/OS facts: process listings and other processes' arguments",
        ";; and environments (kern.proc.*, KERN_PROCARGS2) stay hidden",
        "(allow sysctl-read "
        + " ".join(f'(sysctl-name "{name}")' for name in _SYSCTL_NAMES)
        + ' (sysctl-name-prefix "hw.optional.")'
        + ")",
        ";; metadata only for the parents of readable paths (path resolution needs it)",
        "(allow file-read-metadata "
        + " ".join(f"(literal {_sbpl_path(a)})" for a in ancestors)
        + ")",
        ";; dyld lists the root directory at startup",
        '(allow file-read* (literal "/") '
        + " ".join(f"(literal {_sbpl_path(d)})" for d in _DEVICE_READ)
        + " "
        + " ".join(f"(subpath {_sbpl_path(p)})" for p in allowed)
        + ")",
        '(allow file-write* (literal "/dev/null") '
        + " ".join(f"(subpath {_sbpl_path(p)})" for p in write_paths)
        + ")",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------- memory watchdog


class _RUsageInfoV2(ctypes.Structure):
    """``struct rusage_info_v2`` from <sys/resource.h>."""

    _fields_ = [("ri_uuid", ctypes.c_uint8 * 16)] + [
        (name, ctypes.c_uint64)
        for name in (
            "ri_user_time",
            "ri_system_time",
            "ri_pkg_idle_wkups",
            "ri_interrupt_wkups",
            "ri_pageins",
            "ri_wired_size",
            "ri_resident_size",
            "ri_phys_footprint",
            "ri_proc_start_abstime",
            "ri_proc_exit_abstime",
            "ri_child_user_time",
            "ri_child_system_time",
            "ri_child_pkg_idle_wkups",
            "ri_child_interrupt_wkups",
            "ri_child_pageins",
            "ri_child_elapsed_abstime",
            "ri_diskio_bytesread",
            "ri_diskio_byteswritten",
        )
    ]


_RUSAGE_INFO_V2 = 2
_libproc = None


def process_usage(pid: int) -> tuple[int, int] | None:
    """(physical memory footprint, total bytes written to disk) for ``pid``."""
    global _libproc
    if _libproc is None:
        _libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        _libproc.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        _libproc.proc_pid_rusage.restype = ctypes.c_int
    info = _RUsageInfoV2()
    if _libproc.proc_pid_rusage(pid, _RUSAGE_INFO_V2, ctypes.byref(info)) != 0:
        return None
    return int(info.ri_phys_footprint), int(info.ri_diskio_byteswritten)


# ------------------------------------------------------------------------ backend


class SeatbeltSandbox:
    name = "seatbelt"
    isolation = ISOLATION

    def __init__(self, bundle_dir: Path) -> None:
        self.bundle_dir = Path(os.path.realpath(bundle_dir))

    def available(self) -> tuple[bool, str]:
        if platform.system() != "Darwin":
            return False, "Seatbelt is only available on macOS"
        if not Path(SANDBOX_EXEC).exists():
            return False, f"{SANDBOX_EXEC} not found"
        return True, f"{SANDBOX_EXEC} present (macOS {platform.mac_ver()[0]})"

    def run(self, job: SandboxJob) -> SandboxResult:
        ok, why = self.available()
        if not ok:
            raise SandboxError(why)
        limits = job.limits
        root = Path(os.path.realpath(job.workspace)).parent
        workspace = root / "workspace"
        tmp, out = root / "tmp", root / "out"
        if Path(os.path.realpath(job.workspace)) != workspace or not tmp.is_dir():
            raise SandboxError("job.workspace must be the workspace of a prepared run directory")
        python, reads, execs = python_runtime()
        profile = build_profile(
            read_paths=[*reads, self.bundle_dir, workspace],
            write_paths=[tmp, out],
            exec_paths=execs,
        )
        rlimits = {
            "RLIMIT_CPU": int(limits.cpu_seconds),
            "RLIMIT_FSIZE": int(limits.max_file_mb) * 1024 * 1024,
            "RLIMIT_NOFILE": int(limits.max_open_files),
            "RLIMIT_CORE": 0,
        }
        argv = [
            str(python),
            "-I",
            "-S",
            "-c",
            _LAUNCHER,
            json.dumps(rlimits),
            SANDBOX_EXEC,
            "-p",
            profile,
            str(python),
            "-I",
            "-S",
            "-B",
            str(self.bundle_dir / "bootstrap.py"),
            *job.pytest_args(),
        ]
        results_path = out / RESULTS_FILE
        env = sandbox_env(home=str(tmp), results_path=str(results_path), nonce=job.nonce)
        outcome = run_monitored(
            argv,
            env=env,
            cwd=str(workspace),
            wall_timeout_s=limits.wall_timeout_s,
            keep_output_bytes=limits.output_bytes,
            output_hard_cap_bytes=limits.output_hard_cap_bytes,
            watchdog=_Watchdog(limits, [tmp, out]),
        )
        return finish_result(
            backend=self.name,
            isolation=self.isolation,
            outcome=outcome,
            results_path=results_path,
            nonce=job.nonce,
            signal_limits={24: LIMIT_CPU_TIME, 25: LIMIT_FILE_SIZE},
        )


class _Watchdog:
    def __init__(self, limits: SandboxLimits, scratch: list[Path]) -> None:
        self.memory_bytes = limits.memory_mb * 1024 * 1024
        self.disk_bytes = limits.tmp_mb * 1024 * 1024
        self.write_bytes = limits.disk_write_mb * 1024 * 1024
        self.scratch = scratch
        self.ticks = 0

    def __call__(self, pid: int) -> str | None:
        usage = process_usage(pid)
        if usage is not None:
            footprint, written = usage
            if footprint > self.memory_bytes:
                return LIMIT_MEMORY
            if written > self.write_bytes:
                return LIMIT_DISK
        self.ticks += 1
        if self.ticks % _DISK_CHECK_EVERY == 0:
            used, entries = scratch_usage(self.scratch)
            if used > self.disk_bytes or entries > MAX_SCRATCH_ENTRIES:
                return LIMIT_DISK
        return None
