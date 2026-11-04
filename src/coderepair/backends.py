"""Construct LLM backends by name."""

from __future__ import annotations

import json
from pathlib import Path

from .benchmark.oracle import OracleBackend
from .benchmark.tasks import TaskSpec
from .config import Settings
from .llm.base import BackendError, LLMBackend
from .llm.scripted import ScriptedBackend

BACKEND_NAMES = ("oracle", "scripted", "anthropic", "ollama", "openrouter")
MOCK_BACKENDS = frozenset({"oracle", "scripted"})


def load_script(path: Path) -> list[str]:
    """A script file is a JSON list; each item is a raw response string or a JSON object."""
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list) or not items:
        raise BackendError(f"{path}: expected a non-empty JSON list of responses")
    return [item if isinstance(item, str) else json.dumps(item) for item in items]


def make_backend(
    name: str,
    settings: Settings,
    *,
    task: TaskSpec | None = None,
    script_path: Path | None = None,
) -> LLMBackend:
    if name == "oracle":
        if task is None:
            raise BackendError(
                "the oracle backend only works for benchmark tasks (it replays the gold patch)"
            )
        return OracleBackend(task)
    if name == "scripted":
        if script_path is None:
            raise BackendError("the scripted backend needs --script FILE")
        return ScriptedBackend(load_script(script_path), label=f"scripted:{script_path.name}")
    if name == "anthropic":
        from .llm.anthropic_backend import AnthropicBackend

        return AnthropicBackend(
            settings.anthropic_model,
            effort=settings.anthropic_effort,
            fallbacks=settings.anthropic_fallbacks,
            timeout_s=settings.llm_timeout_s,
        )
    if name == "ollama":
        from .llm.ollama_backend import OllamaBackend

        return OllamaBackend(
            settings.ollama_model, base_url=settings.ollama_url, timeout_s=settings.llm_timeout_s
        )
    if name == "openrouter":
        from .llm.openrouter_backend import OpenRouterBackend

        return OpenRouterBackend(
            settings.openrouter_model,
            base_url=settings.openrouter_url,
            reasoning_effort=settings.openrouter_reasoning,
            data_collection=settings.openrouter_data_collection,
            timeout_s=settings.llm_timeout_s,
        )
    raise BackendError(f"unknown backend {name!r}; choose from {', '.join(BACKEND_NAMES)}")
