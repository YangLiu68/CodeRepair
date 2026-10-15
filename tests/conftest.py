from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from coderepair.config import PROJECT_ROOT, Settings
from coderepair.sandbox.bundle import ensure_runner_bundle
from coderepair.sandbox.docker import DockerSandbox
from coderepair.sandbox.seatbelt import SeatbeltSandbox


def pytest_generate_tests(metafunc):
    """Run every test that takes a ``sandbox`` argument once per backend.

    Backends that are not usable on this machine (no Docker daemon, not macOS)
    are reported as skipped with the reason, never silently dropped.
    """
    if "sandbox" not in metafunc.fixturenames:
        return
    bundle = ensure_runner_bundle(Path(os.path.realpath(PROJECT_ROOT / ".cache")))
    params = []
    for sandbox in (SeatbeltSandbox(bundle), DockerSandbox(bundle)):
        ok, why = sandbox.available()
        marks = [] if ok else [pytest.mark.skip(reason=f"{sandbox.name}: {why}")]
        params.append(pytest.param(sandbox, id=sandbox.name, marks=marks))
    metafunc.parametrize("sandbox", params)


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Never write run artifacts into the project, and ignore the developer's CODEREPAIR_* env."""
    monkeypatch.setenv("CODEREPAIR_RUNS_DIR", str(tmp_path / "runs"))
    for name in (
        "CODEREPAIR_ALLOWED_ROOTS",
        "CODEREPAIR_TASKS_DIR",
        "CODEREPAIR_BACKEND",
        "CODEREPAIR_SANDBOX",
        "CODEREPAIR_SANDBOX_IMAGE",
        "CODEREPAIR_SANDBOX_TIMEOUT_S",
        "CODEREPAIR_SANDBOX_MEMORY_MB",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return replace(Settings.from_env(), runs_dir=tmp_path / "runs")
