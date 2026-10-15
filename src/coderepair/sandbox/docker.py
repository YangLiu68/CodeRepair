"""Container backend: one disposable ``docker run`` per test session.

The container gets:

* ``--network none`` (no interfaces besides loopback, no DNS),
* a non-root user (the invoking user's uid/gid, or ``65534`` if that is root)
  with all capabilities dropped and ``no-new-privileges``; Docker's default
  seccomp profile stays on. Using the host uid lets the container read the
  workspace (mode 0700) and lets the harness delete whatever the run wrote,
* a read-only root filesystem, the workspace and runner bundle mounted
  read-only, a size-limited ``tmpfs`` at ``/tmp`` and one small writable
  directory for the results file,
* memory (no swap), CPU, pids, open-file, file-size and CPU-time limits,
* an explicit environment (no host variables) and no host sockets or
  credentials mounted,
* ``--pull never``: images are pulled ahead of time (``coderepair sandbox pull``),
  never during a run.

The image only needs a stock CPython: pytest comes from the runner bundle.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path

from .base import (
    LIMIT_DISK,
    LIMIT_MEMORY,
    RESULTS_FILE,
    SandboxError,
    SandboxJob,
    SandboxResult,
)
from .common import finish_result, sandbox_env, scratch_usage
from .process import run_monitored

DEFAULT_IMAGE = "python:3.12-slim"
ISOLATION = (
    "Docker container: --network none, non-root, read-only rootfs and workspace, tmpfs /tmp, "
    "CPU/memory/pids limits, all capabilities dropped"
)


def container_user() -> str:
    """The invoking user's uid:gid (never root), so files stay readable and removable."""
    uid, gid = os.getuid(), os.getgid()
    return "65534:65534" if uid == 0 else f"{uid}:{gid}"


_IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9._/:@\-]{0,254}$")
_MOUNT_UNSAFE = re.compile(r"[,=\x00-\x1f\"]")
_CLI_TIMEOUT_S = 30


def _mount(src: Path, dst: str, *, readonly: bool) -> str:
    text = str(src)
    if _MOUNT_UNSAFE.search(text):
        raise SandboxError(f"path cannot be bind-mounted safely: {text!r}")
    spec = f"type=bind,source={text},target={dst}"
    return spec + (",readonly" if readonly else "")


def build_run_argv(
    job: SandboxJob,
    *,
    container_name: str,
    image: str,
    bundle_dir: Path,
    out_dir: Path,
    docker_bin: str = "docker",
    user: str | None = None,
) -> list[str]:
    """The complete ``docker run`` command line for ``job`` (pure; unit-tested)."""
    if not _IMAGE_RE.match(image):
        raise SandboxError(f"invalid image reference {image!r}")
    limits = job.limits
    env = sandbox_env(
        home="/tmp",  # noqa: S108 - the container's own tmpfs
        results_path=f"/out/{RESULTS_FILE}",
        nonce=job.nonce,
    )
    argv = [
        docker_bin,
        "run",
        "--name",
        container_name,
        "--label",
        "coderepair.sandbox=1",
        "--pull",
        "never",
        "--network",
        "none",
        "--user",
        user or container_user(),
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--ipc",
        "none",
        "--hostname",
        "sandbox",
        "--init",  # a real PID 1, so signals and rlimit kills behave as on the host
        "--memory",
        f"{limits.memory_mb}m",
        "--memory-swap",
        f"{limits.memory_mb}m",
        "--cpus",
        "1",
        "--pids-limit",
        str(limits.max_processes),
        "--ulimit",
        f"nofile={limits.max_open_files}:{limits.max_open_files}",
        "--ulimit",
        f"fsize={limits.max_file_mb * 1024 * 1024}:{limits.max_file_mb * 1024 * 1024}",
        "--ulimit",
        f"cpu={limits.cpu_seconds}:{limits.cpu_seconds}",
        "--ulimit",
        "core=0:0",
        "--tmpfs",
        f"/tmp:rw,nosuid,nodev,noexec,size={limits.tmp_mb}m,mode=1777",  # noqa: S108
        "--mount",
        _mount(job.workspace, "/workspace", readonly=True),
        "--mount",
        _mount(bundle_dir, "/opt/coderepair", readonly=True),
        "--mount",
        _mount(out_dir, "/out", readonly=False),
        "--workdir",
        "/workspace",
        "--entrypoint",
        "python3",
    ]
    for key, value in env.items():
        argv += ["--env", f"{key}={value}"]
    argv += [
        image,
        "-I",
        "-S",
        "-B",
        "/opt/coderepair/bootstrap.py",
        *job.pytest_args(),
    ]
    return argv


class DockerSandbox:
    name = "docker"
    isolation = ISOLATION

    def __init__(self, bundle_dir: Path, *, image: str = DEFAULT_IMAGE, docker_bin: str = "docker"):
        self.bundle_dir = Path(os.path.realpath(bundle_dir))
        self.image = image
        self.docker_bin = docker_bin

    def _docker(self, *args: str, timeout: float = _CLI_TIMEOUT_S) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(  # noqa: S603 - fixed docker CLI invocation
                [self.docker_bin, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess([self.docker_bin, *args], -1, "", str(exc))

    def available(self) -> tuple[bool, str]:
        if shutil.which(self.docker_bin) is None:
            return False, f"{self.docker_bin} CLI not found"
        version = self._docker("version", "--format", "{{.Server.Version}}")
        if version.returncode != 0:
            return False, f"docker daemon not reachable: {version.stderr.strip()[:200]}"
        image = self._docker("image", "inspect", "--format", "{{.Id}}", self.image)
        if image.returncode != 0:
            return False, (
                f"docker {version.stdout.strip()} is running but image {self.image} is not "
                "present; run `coderepair sandbox pull`"
            )
        return True, f"docker {version.stdout.strip()}, image {self.image}"

    def pull(self) -> subprocess.CompletedProcess:
        return self._docker("pull", self.image, timeout=900)

    def run(self, job: SandboxJob) -> SandboxResult:
        root = Path(os.path.realpath(job.workspace)).parent
        out = root / "out"
        if not out.is_dir():
            raise SandboxError("job.workspace must be the workspace of a prepared run directory")
        name = f"coderepair-{secrets.token_hex(6)}"
        argv = build_run_argv(
            job,
            container_name=name,
            image=self.image,
            bundle_dir=self.bundle_dir,
            out_dir=out,
            docker_bin=self.docker_bin,
        )
        try:
            outcome = run_monitored(
                argv,
                env=_docker_client_env(),
                cwd=str(root),
                wall_timeout_s=job.limits.wall_timeout_s,
                keep_output_bytes=job.limits.output_bytes,
                output_hard_cap_bytes=job.limits.output_hard_cap_bytes,
                watchdog=_OutputDirWatchdog(out, job.limits.tmp_mb),
                watchdog_interval_s=0.1,
                on_kill=lambda: self._docker("kill", name),
            )
            state = self._inspect_state(name)
        finally:
            self._docker("rm", "--force", "--volumes", name)
        problems = []
        if state is None:
            problems.append("container state unavailable (docker inspect failed)")
        limit = LIMIT_MEMORY if state and state.get("OOMKilled") else None
        exit_code = outcome.returncode
        if state is not None and outcome.limit_exceeded is None:
            exit_code = state.get("ExitCode", exit_code)
        outcome.returncode = exit_code
        if exit_code == 125 and outcome.limit_exceeded is None:
            problems.append(f"docker failed to start the container: {outcome.stderr[-300:]}")
        return finish_result(
            backend=self.name,
            isolation=self.isolation,
            outcome=outcome,
            results_path=out / RESULTS_FILE,
            nonce=job.nonce,
            # Inside the container the shell is absent; signals show up as 128 + n.
            signal_limits={},
            extra_problems=problems,
            limit_override=limit or _exit_code_limit(exit_code),
        )

    def _inspect_state(self, name: str) -> dict | None:
        proc = self._docker("inspect", "--format", "{{json .State}}", name)
        if proc.returncode != 0:
            return None
        try:
            state = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return None
        return state if isinstance(state, dict) else None


class _OutputDirWatchdog:
    """``/out`` is the one host directory the container can write: cap its size."""

    def __init__(self, out: Path, limit_mb: int) -> None:
        self.out = out
        self.limit = limit_mb * 1024 * 1024

    def __call__(self, _pid: int) -> str | None:
        used, entries = scratch_usage([self.out])
        return LIMIT_DISK if used > self.limit or entries > 1_000 else None


def _exit_code_limit(exit_code: int | None) -> str | None:
    # Processes killed by a signal inside the container exit with 128 + signal.
    return {128 + 24: "cpu-time", 128 + 25: "file-size"}.get(exit_code or 0)


def _docker_client_env() -> dict[str, str]:
    """Environment for the docker *client* (host side). Nothing here reaches the container."""
    keep = ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "XDG_RUNTIME_DIR")
    return {k: v for k, v in os.environ.items() if k in keep}
