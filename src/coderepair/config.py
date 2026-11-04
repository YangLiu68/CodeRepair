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
    public_tasks_dir: Path = PROJECT_ROOT / "benchmarks" / "public"
    hard_tasks_dir: Path = PROJECT_ROOT / "benchmarks" / "hard"
    backend: str = "oracle"
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "high"
    anthropic_fallbacks: bool = True
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    openrouter_model: str = "anthropic/claude-sonnet-5.5"
    openrouter_url: str = "https://openrouter.ai/api/v1"
    openrouter_reasoning: str = ""
    openrouter_data_collection: str = "deny"
    llm_timeout_s: int = 300
    fixture_test_timeout_s: int = 120
    limits: Limits = field(default_factory=Limits)
    cache_dir: Path = PROJECT_ROOT / ".cache"
    sandbox: str = "auto"
    sandbox_image: str = "python:3.12-slim"
    sandbox_timeout_s: int = 60
    sandbox_memory_mb: int = 512

    @property
    def task_dirs(self) -> tuple[Path, ...]:
        """Benchmark suites: first-party fixtures, the public (QuixBugs) subset, the hard tier."""
        suites = (self.tasks_dir, self.public_tasks_dir, self.hard_tasks_dir)
        return tuple(d for d in suites if d.is_dir())

    def sandbox_limits(self):
        from .sandbox.base import SandboxLimits

        return SandboxLimits(
            wall_timeout_s=float(self.sandbox_timeout_s),
            cpu_seconds=self.sandbox_timeout_s,
            memory_mb=self.sandbox_memory_mb,
        )

    @classmethod
    def from_env(cls) -> Settings:
        tasks_dir = _env_path("CODEREPAIR_TASKS_DIR", PROJECT_ROOT / "benchmarks" / "tasks")
        public_dir = _env_path(
            "CODEREPAIR_PUBLIC_TASKS_DIR", PROJECT_ROOT / "benchmarks" / "public"
        )
        hard_dir = _env_path("CODEREPAIR_HARD_TASKS_DIR", PROJECT_ROOT / "benchmarks" / "hard")
        roots_env = os.environ.get("CODEREPAIR_ALLOWED_ROOTS", "").strip()
        if roots_env:
            allowed = tuple(Path(p).expanduser() for p in roots_env.split(os.pathsep) if p)
        else:
            allowed = (tasks_dir, public_dir, hard_dir)
        return cls(
            tasks_dir=tasks_dir,
            public_tasks_dir=public_dir,
            hard_tasks_dir=hard_dir,
            runs_dir=_env_path("CODEREPAIR_RUNS_DIR", PROJECT_ROOT / "runs"),
            allowed_roots=allowed,
            backend=os.environ.get("CODEREPAIR_BACKEND", "oracle").strip() or "oracle",
            anthropic_model=os.environ.get("CODEREPAIR_ANTHROPIC_MODEL", "claude-opus-5-5"),
            anthropic_effort=os.environ.get("CODEREPAIR_ANTHROPIC_EFFORT", "high"),
            anthropic_fallbacks=os.environ.get("CODEREPAIR_ANTHROPIC_FALLBACKS", "1") != "0",
            ollama_url=os.environ.get("CODEREPAIR_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=os.environ.get("CODEREPAIR_OLLAMA_MODEL", "qwen2.5:7b"),
            openrouter_model=os.environ.get(
                "CODEREPAIR_OPENROUTER_MODEL", "anthropic/claude-sonnet-5.5"
            ).strip()
            or "anthropic/claude-sonnet-5.5",
            openrouter_url=os.environ.get(
                "CODEREPAIR_OPENROUTER_URL", "https://openrouter.ai/api/v1"
            ).strip()
            or "https://openrouter.ai/api/v1",
            openrouter_reasoning=os.environ.get("CODEREPAIR_OPENROUTER_REASONING", "").strip(),
            openrouter_data_collection=os.environ.get(
                "CODEREPAIR_OPENROUTER_DATA_COLLECTION", "deny"
            ).strip()
            or "deny",
            llm_timeout_s=_env_int("CODEREPAIR_LLM_TIMEOUT_S", 300),
            fixture_test_timeout_s=_env_int("CODEREPAIR_FIXTURE_TEST_TIMEOUT_S", 120),
            cache_dir=_env_path("CODEREPAIR_CACHE_DIR", PROJECT_ROOT / ".cache"),
            sandbox=os.environ.get("CODEREPAIR_SANDBOX", "auto").strip() or "auto",
            sandbox_image=os.environ.get("CODEREPAIR_SANDBOX_IMAGE", "python:3.12-slim").strip()
            or "python:3.12-slim",
            sandbox_timeout_s=_env_int("CODEREPAIR_SANDBOX_TIMEOUT_S", 60),
            sandbox_memory_mb=_env_int("CODEREPAIR_SANDBOX_MEMORY_MB", 512),
        )
