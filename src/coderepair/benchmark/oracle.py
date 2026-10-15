"""ORACLE backend: replays a task's gold solution.

This is a harness-side test double used to check that the pipeline (prompting,
parsing, validation, diffing, tracing) works end to end without an API key.
It reads the hidden reference solution, so its results are NEVER a repair
metric and are excluded from every benchmark table.
"""

from __future__ import annotations

from ..llm.base import LLMRequest, LLMResponse, estimate_tokens
from .tasks import TaskSpec


class OracleBackend:
    name = "oracle"
    is_mock = True

    def __init__(self, task: TaskSpec) -> None:
        self._solution_json = task.solution_path.read_text(encoding="utf-8")
        self.requests: list[LLMRequest] = []

    @property
    def model(self) -> str:
        return "gold-solution replay (not a model)"

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            text=self._solution_json,
            model=self.model,
            input_tokens=estimate_tokens(request.system + request.user),
            output_tokens=estimate_tokens(self._solution_json),
            usage_is_estimate=True,
            stop_reason="end_turn",
            metadata={"oracle": True},
        )
