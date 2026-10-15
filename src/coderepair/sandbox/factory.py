"""Choose a sandbox backend. There is deliberately no unsandboxed fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .base import Sandbox, SandboxUnavailable
from .bundle import ensure_runner_bundle
from .docker import DEFAULT_IMAGE, DockerSandbox
from .seatbelt import SeatbeltSandbox

SANDBOX_NAMES = ("auto", "docker", "seatbelt")


@dataclass(frozen=True)
class BackendStatus:
    name: str
    available: bool
    detail: str
    isolation: str


def _candidates(cache_dir: Path, image: str) -> list[Sandbox]:
    bundle = ensure_runner_bundle(cache_dir)
    return [DockerSandbox(bundle, image=image), SeatbeltSandbox(bundle)]


def sandbox_status(cache_dir: Path, image: str = DEFAULT_IMAGE) -> list[BackendStatus]:
    statuses = []
    for sandbox in _candidates(cache_dir, image):
        ok, detail = sandbox.available()
        statuses.append(BackendStatus(sandbox.name, ok, detail, sandbox.isolation))
    return statuses


def make_sandbox(name: str, cache_dir: Path, image: str = DEFAULT_IMAGE) -> Sandbox:
    """Return the requested backend, or for ``auto`` the strongest available one.

    ``auto`` prefers a container and falls back to Seatbelt on macOS. If no
    backend is usable this raises :class:`SandboxUnavailable`; callers must not
    run the code some other way.
    """
    if name not in SANDBOX_NAMES:
        choices = ", ".join(SANDBOX_NAMES)
        raise SandboxUnavailable(f"unknown sandbox {name!r}; choose from {choices}")
    reasons = []
    for sandbox in _candidates(cache_dir, image):
        if name not in ("auto", sandbox.name):
            continue
        ok, detail = sandbox.available()
        if ok:
            return sandbox
        reasons.append(f"{sandbox.name}: {detail}")
    raise SandboxUnavailable(
        "no sandbox available, so no repository code will be run ("
        + "; ".join(reasons)
        + "). Install Docker (or Colima) or use macOS."
    )
