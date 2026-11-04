"""Backend interface shared by real and mock LLMs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class BackendError(RuntimeError):
    def __init__(
        self, message: str, *, retryable: bool = False, cost_usd: float | None = None
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        #: what a failed but billed call cost (e.g. a response truncated at max_tokens)
        self.cost_usd = cost_usd


@dataclass(frozen=True)
class LLMRequest:
    system: str
    user: str
    response_schema: dict
    #: 0 asks for the backend's most deterministic answer; n > 0 asks for an independent
    #: sample (backends that support it use temperature > 0 with seed n).
    sample_index: int = 0


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    usage_is_estimate: bool = False
    latency_s: float = 0.0
    stop_reason: str | None = None
    request_id: str | None = None
    metadata: dict = field(default_factory=dict)


class LLMBackend(Protocol):
    name: str
    #: True for backends that do not call a language model (oracle / scripted).
    is_mock: bool

    @property
    def model(self) -> str: ...

    def complete(self, request: LLMRequest) -> LLMResponse: ...


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 characters per token) for backends that report no usage."""
    return max(1, len(text) // 4)
