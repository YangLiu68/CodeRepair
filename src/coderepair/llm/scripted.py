"""Deterministic mock backend that replays canned responses (for tests and demos)."""

from __future__ import annotations

from .base import BackendError, LLMRequest, LLMResponse, estimate_tokens


class ScriptedBackend:
    """Returns the given responses in order and records every request it receives."""

    name = "scripted"
    is_mock = True

    def __init__(self, responses: list[str], *, label: str = "scripted-mock") -> None:
        self._responses = list(responses)
        self._label = label
        self.requests: list[LLMRequest] = []

    @property
    def model(self) -> str:
        return self._label

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self._responses:
            raise BackendError("scripted backend has no responses left")
        text = self._responses.pop(0)
        return LLMResponse(
            text=text,
            model=self._label,
            input_tokens=estimate_tokens(request.system + request.user),
            output_tokens=estimate_tokens(text),
            usage_is_estimate=True,
            stop_reason="end_turn",
        )
