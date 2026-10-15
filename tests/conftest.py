from __future__ import annotations

from dataclasses import replace

import pytest

from coderepair.config import Settings


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Never write run artifacts into the project, and ignore the developer's CODEREPAIR_* env."""
    monkeypatch.setenv("CODEREPAIR_RUNS_DIR", str(tmp_path / "runs"))
    for name in ("CODEREPAIR_ALLOWED_ROOTS", "CODEREPAIR_TASKS_DIR", "CODEREPAIR_BACKEND"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return replace(Settings.from_env(), runs_dir=tmp_path / "runs")
