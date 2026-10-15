"""Claude backend (optional; install with ``pip install 'coderepair[anthropic]'``).

One Messages API call per proposal. The response is constrained with structured
outputs (``output_config.format``) to the patch-proposal JSON schema, so no tool
call is needed. Server-side refusal fallback (``fallbacks="default"``) is enabled
by default; disable with ``CODEREPAIR_ANTHROPIC_FALLBACKS=0``.
"""

from __future__ import annotations

import time
from typing import Any

from .base import BackendError, LLMRequest, LLMResponse

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicBackend:
    name = "anthropic"
    is_mock = False

    def __init__(
        self,
        model: str = "claude-opus-5-5",
        *,
        effort: str = "high",
        max_tokens: int = 16000,
        fallbacks: bool = True,
        timeout_s: float = 300,
        client: Any = None,
    ) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise BackendError(
                "the anthropic backend needs the optional dependency: "
                "pip install 'coderepair[anthropic]'"
            ) from exc
        self._anthropic = anthropic
        # With no explicit client the SDK resolves credentials itself
        # (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or an `ant auth login` profile).
        self._client = client or anthropic.Anthropic(timeout=timeout_s)
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens
        self._fallbacks = fallbacks

    @property
    def model(self) -> str:
        return self._model

    def complete(self, request: LLMRequest) -> LLMResponse:
        anthropic = self._anthropic
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
            "output_config": {
                "effort": self._effort,
                "format": {"type": "json_schema", "schema": request.response_schema},
            },
        }
        if self._fallbacks:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"

        start = time.monotonic()
        try:
            message = self._client.beta.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise BackendError(f"authentication failed: {exc.message}") from exc
        except anthropic.RateLimitError as exc:
            raise BackendError(f"rate limited: {exc.message}", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise BackendError(
                f"API error {exc.status_code}: {exc.message}", retryable=exc.status_code >= 500
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise BackendError(f"connection error: {exc}", retryable=True) from exc
        latency = time.monotonic() - start

        request_id = getattr(message, "_request_id", None)
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise BackendError(
                f"model declined the request (category: {category}, request {request_id})"
            )
        if message.stop_reason == "max_tokens":
            raise BackendError(f"response truncated at max_tokens (request {request_id})")
        text = next((block.text for block in message.content if block.type == "text"), None)
        if text is None:
            raise BackendError(f"response contained no text block (request {request_id})")

        usage = message.usage
        iterations = getattr(usage, "iterations", None) or []
        fallback_ran = any(
            getattr(entry, "type", None) == "fallback_message" for entry in iterations
        )
        return LLMResponse(
            text=text,
            model=message.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            usage_is_estimate=False,
            latency_s=latency,
            stop_reason=message.stop_reason,
            request_id=request_id,
            metadata={
                "effort": self._effort,
                "fallback_ran": fallback_ran,
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
            },
        )
