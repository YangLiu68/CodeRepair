"""Runtime settings, read from environment variables (documented in .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else default


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


@dataclass(frozen=True)
class Limits:
    """Hard limits that keep ingestion, prompts and patches small and reviewable."""

    max_file_bytes: int = 200_000
    max_files: int = 2_000
    max_total_bytes: int = 5_000_000
    context_char_budget: int = 60_000
    max_context_source_files: int = 3
    max_context_test_files: int = 2
    max_edits: int = 20
    max_changed_lines: int = 200
    max_edit_chars: int = 20_000


@dataclass(frozen=True)
class Settings:
    tasks_dir: Path
    runs_dir: Path
    allowed_roots: tuple[Path, ...]
    backend: str = "oracle"
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "high"
    anthropic_fallbacks: bool = True
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    llm_timeout_s: int = 300
    fixture_test_timeout_s: int = 120
    limits: Limits = field(default_factory=Limits)

    @classmethod
    def from_env(cls) -> Settings:
        tasks_dir = _env_path("CODEREPAIR_TASKS_DIR", PROJECT_ROOT / "benchmarks" / "tasks")
        roots_env = os.environ.get("CODEREPAIR_ALLOWED_ROOTS", "").strip()
        if roots_env:
            allowed = tuple(Path(p).expanduser() for p in roots_env.split(os.pathsep) if p)
        else:
            allowed = (tasks_dir,)
        return cls(
            tasks_dir=tasks_dir,
            runs_dir=_env_path("CODEREPAIR_RUNS_DIR", PROJECT_ROOT / "runs"),
            allowed_roots=allowed,
            backend=os.environ.get("CODEREPAIR_BACKEND", "oracle").strip() or "oracle",
            anthropic_model=os.environ.get("CODEREPAIR_ANTHROPIC_MODEL", "claude-opus-5-5"),
            anthropic_effort=os.environ.get("CODEREPAIR_ANTHROPIC_EFFORT", "high"),
            anthropic_fallbacks=os.environ.get("CODEREPAIR_ANTHROPIC_FALLBACKS", "1") != "0",
            ollama_url=os.environ.get("CODEREPAIR_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=os.environ.get("CODEREPAIR_OLLAMA_MODEL", "qwen2.5:7b"),
            llm_timeout_s=_env_int("CODEREPAIR_LLM_TIMEOUT_S", 300),
            fixture_test_timeout_s=_env_int("CODEREPAIR_FIXTURE_TEST_TIMEOUT_S", 120),
        )
