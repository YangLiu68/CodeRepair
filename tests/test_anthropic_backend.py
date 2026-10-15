from __future__ import annotations

import json

import pytest

from coderepair.llm.base import BackendError, LLMRequest
from coderepair.patch import PROPOSAL_JSON_SCHEMA

REQUEST = LLMRequest("system text", "user text", PROPOSAL_JSON_SCHEMA)
PROPOSAL_TEXT = json.dumps({"summary": "fix", "edits": []})

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")


def _anthropic_client(handler):
    return anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )


def _message(stop_reason="end_turn", text=PROPOSAL_TEXT, **extra):
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 80},
        **extra,
    }


def test_anthropic_backend_request_shape_and_response_parsing():
    from coderepair.llm.anthropic_backend import AnthropicBackend

    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["beta"] = request.headers.get("anthropic-beta")
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=_message(), headers={"request-id": "req_123"})

    backend = AnthropicBackend(client=_anthropic_client(handler))
    response = backend.complete(REQUEST)

    body = seen["body"]
    assert seen["path"] == "/v1/messages"
    assert seen["beta"] == "server-side-fallback-2026-07-01"
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert body["system"] == "system text"
    assert body["messages"] == [{"role": "user", "content": "user text"}]
    assert body["output_config"] == {
        "effort": "high",
        "format": {"type": "json_schema", "schema": PROPOSAL_JSON_SCHEMA},
    }
    assert "temperature" not in body and "thinking" not in body and "tool_choice" not in body
    assert response.text == PROPOSAL_TEXT
    assert (response.input_tokens, response.output_tokens) == (1200, 80)
    assert response.request_id == "req_123"
    assert not response.usage_is_estimate and not backend.is_mock


def test_anthropic_backend_without_fallbacks_sends_no_beta():
    from coderepair.llm.anthropic_backend import AnthropicBackend

    seen = {}

    def handler(request):
        seen["beta"] = request.headers.get("anthropic-beta")
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=_message())

    AnthropicBackend(client=_anthropic_client(handler), fallbacks=False).complete(REQUEST)
    assert seen["beta"] is None and "fallbacks" not in seen["body"]


@pytest.mark.parametrize(
    ("message", "match"),
    [
        (
            _message(
                stop_reason="refusal",
                text="",
                stop_details={"type": "refusal", "category": "cyber", "explanation": None},
            ),
            "declined",
        ),
        (_message(stop_reason="max_tokens"), "truncated"),
    ],
)
def test_anthropic_backend_stop_reasons(message, match):
    from coderepair.llm.anthropic_backend import AnthropicBackend

    backend = AnthropicBackend(
        client=_anthropic_client(lambda r: httpx2.Response(200, json=message))
    )
    with pytest.raises(BackendError, match=match):
        backend.complete(REQUEST)


@pytest.mark.parametrize(
    ("status", "retryable", "match"),
    [
        (401, False, "authentication"),
        (429, True, "rate limited"),
        (500, True, "API error 500"),
        (400, False, "API error 400"),
    ],
)
def test_anthropic_backend_http_errors(status, retryable, match):
    from coderepair.llm.anthropic_backend import AnthropicBackend

    def handler(request):
        return httpx2.Response(
            status, json={"type": "error", "error": {"type": "x", "message": "nope"}}
        )

    with pytest.raises(BackendError, match=match) as info:
        AnthropicBackend(client=_anthropic_client(handler)).complete(REQUEST)
    assert info.value.retryable is retryable
