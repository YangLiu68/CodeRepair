"""OpenRouter backend against a mocked HTTP transport (no network, no key needed)."""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from coderepair.backends import make_backend
from coderepair.llm.base import BackendError, LLMRequest
from coderepair.llm.openrouter_backend import OpenRouterBackend
from coderepair.patch import PROPOSAL_JSON_SCHEMA

REQUEST = LLMRequest("system text", "user text", PROPOSAL_JSON_SCHEMA)
PROPOSAL_TEXT = json.dumps({"summary": "fix", "edits": []})
KEY = "sk-or-v1-" + "0123456789abcdef" * 4
CLAUDE_PARAMS = ["max_tokens", "reasoning", "response_format", "structured_outputs", "tools"]
OPEN_PARAMS = ["max_tokens", "response_format", "seed", "structured_outputs", "temperature"]


def _endpoints(*param_lists):
    return {
        "data": {
            "id": "vendor/model",
            "endpoints": [{"supported_parameters": params} for params in param_lists],
        }
    }


def _completion(text=PROPOSAL_TEXT, finish="stop", **extra):
    body = {
        "id": "gen-1",
        "model": "vendor/model",
        "provider": "SomeCloud",
        "choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": text}}],
        "usage": {
            "prompt_tokens": 900,
            "completion_tokens": 40,
            "cost": 0.0021,
            "prompt_tokens_details": {"cached_tokens": 0},
            "completion_tokens_details": {"reasoning_tokens": 12},
        },
    }
    body.update(extra)
    return body


class _Server:
    """Records requests; answers the endpoint lookup and replays chat responses in order."""

    def __init__(self, *chat, params=(CLAUDE_PARAMS,)):
        self.chat = list(chat)
        self.params = params
        self.posts: list[dict] = []
        self.gets: list[str] = []
        self.headers: list[httpx.Headers] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.headers.append(request.headers)
        if request.method == "GET":
            self.gets.append(request.url.path)
            return httpx.Response(200, json=_endpoints(*self.params))
        self.posts.append(json.loads(request.content))
        status, body = self.chat.pop(0)
        return httpx.Response(status, json=body)


def _backend(server, **kwargs) -> tuple[OpenRouterBackend, list[float]]:
    sleeps: list[float] = []
    backend = OpenRouterBackend(
        "vendor/model",
        api_key=KEY,
        client=httpx.Client(transport=httpx.MockTransport(server)),
        sleep=sleeps.append,
        **kwargs,
    )
    return backend, sleeps


def test_request_shape_and_response_for_a_model_without_sampling_parameters():
    server = _Server((200, _completion()), (200, _completion()))
    backend, _ = _backend(server)
    response = backend.complete(REQUEST)
    backend.complete(replace(REQUEST, sample_index=2))

    assert server.gets == ["/api/v1/models/vendor/model/endpoints"]  # looked up once
    body = server.posts[0]
    assert body["model"] == "vendor/model"
    assert body["messages"] == [
        {"role": "system", "content": "system text"},
        {"role": "user", "content": "user text"},
    ]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"] == PROPOSAL_JSON_SCHEMA
    assert body["provider"] == {"require_parameters": True, "data_collection": "deny"}
    for sent in server.posts:  # Claude-like endpoints accept neither, so neither is sent
        assert "temperature" not in sent and "seed" not in sent and "reasoning" not in sent
    assert all(h["authorization"] == f"Bearer {KEY}" for h in server.headers)

    assert response.text == PROPOSAL_TEXT
    assert (response.input_tokens, response.output_tokens) == (900, 40)
    assert response.request_id == "gen-1" and response.stop_reason == "stop"
    assert response.metadata["cost_usd"] == 0.0021
    assert response.metadata["provider"] == "SomeCloud"
    assert response.metadata["reasoning_tokens"] == 12
    assert response.metadata["sampling"].startswith("provider default")
    assert not response.usage_is_estimate


def test_sampling_parameters_are_sent_when_a_schema_capable_endpoint_accepts_them():
    # The second endpoint has temperature but no structured outputs: it does not count.
    server = _Server(
        (200, _completion()),
        (200, _completion()),
        params=(OPEN_PARAMS, ["temperature", "top_p", "max_tokens"]),
    )
    backend, _ = _backend(server, reasoning_effort="low")
    first = backend.complete(REQUEST)
    second = backend.complete(replace(REQUEST, sample_index=2))
    assert (server.posts[0]["temperature"], server.posts[0]["seed"]) == (0, 0)
    assert (server.posts[1]["temperature"], server.posts[1]["seed"]) == (0.7, 2)
    assert server.posts[0]["reasoning"] == {"effort": "low"}
    assert first.metadata["sampling"] == "temperature 0, seed 0"
    assert second.metadata["sampling"] == "temperature 0.7, seed 2"
    assert backend.config["reasoning_effort"] == "low"

    no_seed = _Server((200, _completion()), params=(["structured_outputs", "temperature"],))
    backend, _ = _backend(no_seed)
    backend.complete(REQUEST)
    assert no_seed.posts[0]["temperature"] == 0 and "seed" not in no_seed.posts[0]


def test_a_model_without_structured_outputs_is_refused_before_any_paid_call():
    server = _Server(params=(["temperature", "max_tokens"],))
    backend, _ = _backend(server)
    with pytest.raises(BackendError, match="structured outputs"):
        backend.complete(REQUEST)
    assert server.posts == []


@pytest.mark.parametrize(
    ("status", "body", "match", "retryable"),
    [
        (401, {"error": {"code": 401, "message": "No auth credentials found"}}, "rejected", False),
        (402, {"error": {"code": 402, "message": "Insufficient credits"}}, "credits", False),
        (400, {"error": {"code": 400, "message": "bad schema"}}, "HTTP 400", False),
        (503, {"error": {"code": 503, "message": "overloaded"}}, "HTTP 503", True),
        # An error reported inside an HTTP 200 body counts as that error.
        (200, {"error": {"code": 502, "message": "upstream failed"}}, "HTTP 502", True),
    ],
)
def test_http_errors(status, body, match, retryable):
    server = _Server(*[(status, body)] * 3)
    backend, sleeps = _backend(server)
    with pytest.raises(BackendError, match=match) as info:
        backend.complete(REQUEST)
    assert info.value.retryable is retryable
    assert KEY not in str(info.value)
    assert len(server.posts) == (3 if retryable else 1)  # two retries for transient errors
    assert sleeps == ([2.0, 8.0] if retryable else [])


def test_a_transient_error_is_retried_and_the_retry_is_recorded():
    server = _Server((429, {"error": {"code": 429, "message": "slow down"}}), (200, _completion()))
    backend, sleeps = _backend(server)
    response = backend.complete(REQUEST)
    assert response.text == PROPOSAL_TEXT and response.metadata["retries"] == 1
    assert sleeps == [2.0]


def test_unreachable_server_is_retryable():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=_endpoints(CLAUDE_PARAMS))
        raise httpx.ConnectError("connection refused")

    backend = OpenRouterBackend(
        "vendor/model",
        api_key=KEY,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _s: None,
    )
    with pytest.raises(BackendError, match="cannot reach") as info:
        backend.complete(REQUEST)
    assert info.value.retryable


@pytest.mark.parametrize(
    ("body", "match"),
    [
        (_completion(finish="length"), "truncated"),
        (_completion(finish="content_filter"), "declined"),
        (_completion(text=""), "no text"),
        (_completion(choices=[]), "unexpected"),
        (_completion(choices=[{"finish_reason": "stop", "message": None}]), "unexpected"),
    ],
)
def test_unusable_answers_raise_and_keep_their_cost(body, match):
    backend, _ = _backend(_Server((200, body)))
    with pytest.raises(BackendError, match=match) as info:
        backend.complete(REQUEST)
    assert info.value.cost_usd == 0.0021  # billed, so the benchmark still counts it
    assert not info.value.retryable


def test_refusal_field_counts_as_declined():
    body = _completion()
    body["choices"][0]["message"]["refusal"] = "I can't help with that"
    backend, _ = _backend(_Server((200, body)))
    with pytest.raises(BackendError, match="declined"):
        backend.complete(REQUEST)


def test_key_handling(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(BackendError, match="OPENROUTER_API_KEY"):
        OpenRouterBackend("vendor/model")
    monkeypatch.setenv("OPENROUTER_API_KEY", f"  {KEY}\n")
    backend = OpenRouterBackend("vendor/model")
    assert KEY not in repr(backend)
    # The key is only ever sent over https (plain http only to this machine, for tests).
    for url in ("http://openrouter.ai/api/v1", "ftp://example.com", "openrouter.ai/api/v1"):
        with pytest.raises(BackendError, match="https"):
            OpenRouterBackend("vendor/model", base_url=url)
    OpenRouterBackend("vendor/model", base_url="http://127.0.0.1:9/api/v1")
    with pytest.raises(BackendError, match="data_collection"):
        OpenRouterBackend("vendor/model", data_collection="maybe")


def test_make_backend_reads_settings(settings, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    custom = replace(
        settings,
        openrouter_model="anthropic/claude-haiku-5.5",
        openrouter_reasoning="medium",
        openrouter_data_collection="allow",
    )
    backend = make_backend("openrouter", custom)
    assert isinstance(backend, OpenRouterBackend) and not backend.is_mock
    assert backend.model == "anthropic/claude-haiku-5.5"
    assert backend.config == {
        "reasoning_effort": "medium",
        "data_collection": "allow",
        "max_tokens": 16000,
    }
