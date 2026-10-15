"""Local model backend using Ollama's native chat API with JSON-schema constrained output.

Runs fully offline against a model served on this machine (default
``http://127.0.0.1:11434``). Repository content is sent only to that server.
"""

from __future__ import annotations

import time

import httpx

from .base import BackendError, LLMRequest, LLMResponse


class OllamaBackend:
    name = "ollama"
    is_mock = False

    def __init__(
        self,
        model: str = "qwen2.5:7b",
        *,
        base_url: str = "http://127.0.0.1:11434",
        timeout_s: float = 300,
        num_ctx: int = 16384,
        client: httpx.Client | None = None,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._num_ctx = num_ctx
        self._client = client or httpx.Client(timeout=timeout_s, trust_env=False)

    @property
    def model(self) -> str:
        return self._model

    def unload(self) -> None:
        """Ask the server to drop the model from memory now (keep_alive=0); best effort."""
        try:
            self._client.post(
                f"{self._base_url}/api/generate", json={"model": self._model, "keep_alive": 0}
            )
        except httpx.HTTPError:
            pass

    def complete(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": self._model,
            "stream": False,
            "format": request.response_schema,
            "options": {
                "temperature": 0 if request.sample_index == 0 else 0.7,
                "seed": request.sample_index,
                "num_ctx": self._num_ctx,
            },
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
        }
        start = time.monotonic()
        try:
            response = self._client.post(f"{self._base_url}/api/chat", json=payload)
        except httpx.HTTPError as exc:
            raise BackendError(
                f"cannot reach Ollama at {self._base_url}: {exc}", retryable=True
            ) from exc
        latency = time.monotonic() - start
        if response.status_code != 200:
            raise BackendError(
                f"Ollama returned HTTP {response.status_code}: {response.text[:300]}",
                retryable=response.status_code >= 500,
            )
        try:
            data = response.json()
            text = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise BackendError(f"unexpected Ollama response: {response.text[:300]}") from exc
        if data.get("done_reason") == "length":
            raise BackendError("response truncated (done_reason=length)")
        return LLMResponse(
            text=text,
            model=data.get("model", self._model),
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            usage_is_estimate=False,
            latency_s=latency,
            stop_reason=data.get("done_reason"),
            metadata={"num_ctx": self._num_ctx},
        )
