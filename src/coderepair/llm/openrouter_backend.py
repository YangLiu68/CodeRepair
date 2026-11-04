"""Hosted models through OpenRouter's OpenAI-compatible chat completions API.

One call per proposal, constrained to the patch-proposal JSON schema with a strict
``response_format``. ``provider.require_parameters`` restricts routing to endpoints
that honour every parameter sent, so no provider silently ignores the schema, and
``provider.data_collection = "deny"`` (the default) excludes providers that store
or train on prompts. Repository excerpts in the prompt do leave the machine.

Sampling: the agents ask for a deterministic first answer and independent later
samples (``LLMRequest.sample_index``). Many hosted models, all Claude models among
them, accept neither ``temperature`` nor ``seed``. Before the first call the backend
reads the model's endpoint list (a free request) and sends only what a
schema-capable endpoint accepts; otherwise every call uses the provider's default
sampling. Each response records which applied under ``metadata["sampling"]``.

The key comes from ``OPENROUTER_API_KEY`` and is sent only to the configured base
URL, which must be HTTPS (plain HTTP only to a loopback host, for tests).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from .base import BackendError, LLMRequest, LLMResponse

DEFAULT_URL = "https://openrouter.ai/api/v1"
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_RETRY_DELAYS_S = (2.0, 8.0)


def _check_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    if parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in _LOOPBACK):
        return base_url.rstrip("/")
    raise BackendError(f"refusing to send the API key to {base_url!r}: the URL must be https")


class OpenRouterBackend:
    name = "openrouter"
    is_mock = False

    def __init__(
        self,
        model: str = "anthropic/claude-sonnet-5.5",
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_URL,
        reasoning_effort: str = "",
        data_collection: str = "deny",
        max_tokens: int = 16000,
        timeout_s: float = 300,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key = (os.environ.get("OPENROUTER_API_KEY", "") if api_key is None else api_key).strip()
        if not key:
            raise BackendError(
                "the openrouter backend needs OPENROUTER_API_KEY (put it in .env, see .env.example)"
            )
        if data_collection not in ("deny", "allow"):
            raise BackendError(
                f"data_collection must be 'deny' or 'allow', got {data_collection!r}"
            )
        self._base_url = _check_url(base_url)
        self._headers = {"Authorization": f"Bearer {key}"}
        self._model = model
        self._reasoning_effort = reasoning_effort.strip()
        self._data_collection = data_collection
        self._max_tokens = max_tokens
        self._client = client or httpx.Client(timeout=timeout_s)
        self._sleep = sleep
        self._sampling: tuple[bool, bool] | None = None  # (temperature, seed) accepted

    def __repr__(self) -> str:  # never show the key
        return f"OpenRouterBackend(model={self._model!r}, base_url={self._base_url!r})"

    @property
    def model(self) -> str:
        return self._model

    @property
    def config(self) -> dict:
        """Settings that change the model's answers (part of the benchmark fingerprint)."""
        return {
            "reasoning_effort": self._reasoning_effort or "provider-default",
            "data_collection": self._data_collection,
            "max_tokens": self._max_tokens,
        }

    # ------------------------------------------------------------------ capabilities

    def sampling_support(self) -> tuple[bool, bool]:
        """Whether a schema-capable endpoint accepts (``temperature``, ``seed``)."""
        if self._sampling is None:
            slug = self._model.split(":", 1)[0]  # variants such as ":batch" share endpoints
            data = self._get(f"/models/{slug}/endpoints")
            try:
                endpoints = data["data"]["endpoints"]
                capable = [
                    set(ep.get("supported_parameters") or ())
                    for ep in endpoints
                    if "structured_outputs" in (ep.get("supported_parameters") or ())
                ]
            except (KeyError, TypeError, AttributeError) as exc:
                raise BackendError(f"unexpected endpoint list for {self._model}") from exc
            if not capable:
                raise BackendError(
                    f"no OpenRouter endpoint for {self._model} supports structured outputs"
                )
            temperature = any("temperature" in params for params in capable)
            seed = any({"temperature", "seed"} <= params for params in capable)
            self._sampling = (temperature, seed)
        return self._sampling

    # ------------------------------------------------------------------ completion

    def complete(self, request: LLMRequest) -> LLMResponse:
        temperature_ok, seed_ok = self.sampling_support()
        payload: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "patch_proposal",
                    "strict": True,
                    "schema": request.response_schema,
                },
            },
            "provider": {"require_parameters": True, "data_collection": self._data_collection},
            "max_tokens": self._max_tokens,
            "usage": {"include": True},
        }
        if temperature_ok:
            payload["temperature"] = 0 if request.sample_index == 0 else 0.7
            sampling = f"temperature {payload['temperature']}"
            if seed_ok:
                payload["seed"] = request.sample_index
                sampling += f", seed {request.sample_index}"
        else:
            sampling = "provider default (model accepts no temperature)"
        if self._reasoning_effort:
            payload["reasoning"] = {"effort": self._reasoning_effort}

        start = time.monotonic()
        data, retries = self._post_with_retries("/chat/completions", payload)
        latency = time.monotonic() - start

        request_id = data.get("id")
        usage = data.get("usage") or {}
        cost = usage.get("cost") if isinstance(usage.get("cost"), (int, float)) else None
        try:
            choice = data["choices"][0]
            message = choice["message"]
            if not isinstance(message, dict):
                raise TypeError("message is not an object")
        except (KeyError, IndexError, TypeError) as exc:
            raise BackendError(
                f"unexpected OpenRouter response (request {request_id})", cost_usd=cost
            ) from exc
        finish = choice.get("finish_reason")
        if finish == "length":
            raise BackendError(
                f"response truncated at max_tokens (request {request_id})", cost_usd=cost
            )
        if finish == "content_filter" or message.get("refusal"):
            raise BackendError(f"model declined the request (request {request_id})", cost_usd=cost)
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise BackendError(f"response contained no text (request {request_id})", cost_usd=cost)

        details = usage.get("completion_tokens_details") or {}
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
        return LLMResponse(
            text=text,
            model=data.get("model", self._model),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            usage_is_estimate=False,
            latency_s=latency,
            stop_reason=finish,
            request_id=request_id,
            metadata={
                "provider": data.get("provider"),
                "cost_usd": cost,
                "reasoning_tokens": details.get("reasoning_tokens"),
                "cached_tokens": cached,
                "reasoning_effort": self._reasoning_effort or "provider-default",
                "sampling": sampling,
                "retries": retries,
            },
        )

    # ------------------------------------------------------------------ HTTP

    def _get(self, path: str) -> dict:
        try:
            response = self._client.get(f"{self._base_url}{path}", headers=self._headers)
        except httpx.HTTPError as exc:
            raise BackendError(f"cannot reach OpenRouter: {exc}", retryable=True) from exc
        return self._json_or_raise(response)

    def _post_with_retries(self, path: str, payload: dict) -> tuple[dict, int]:
        for attempt in range(len(_RETRY_DELAYS_S) + 1):
            try:
                try:
                    response = self._client.post(
                        f"{self._base_url}{path}", headers=self._headers, json=payload
                    )
                except httpx.HTTPError as exc:
                    raise BackendError(f"cannot reach OpenRouter: {exc}", retryable=True) from exc
                return self._json_or_raise(response), attempt
            except BackendError as exc:
                if not exc.retryable or attempt == len(_RETRY_DELAYS_S):
                    raise
                self._sleep(_RETRY_DELAYS_S[attempt])
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _json_or_raise(response: httpx.Response) -> dict:
        try:
            data = response.json()
        except ValueError:
            data = None
        error = data.get("error") if isinstance(data, dict) else None
        if response.status_code == 200 and isinstance(data, dict) and not error:
            return data
        status = response.status_code
        if isinstance(error, dict):
            status = error.get("code") if isinstance(error.get("code"), int) else status
            message = str(error.get("message", ""))[:300]
        else:
            message = response.text[:300]
        if status in (401, 403):
            raise BackendError(f"OpenRouter rejected the key (HTTP {status}): {message}")
        if status == 402:
            raise BackendError(f"OpenRouter: not enough credits (HTTP 402): {message}")
        raise BackendError(
            f"OpenRouter error (HTTP {status}): {message}",
            retryable=status in (408, 429) or status >= 500,
        )
