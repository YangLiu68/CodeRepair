from __future__ import annotations

import json

import httpx
import pytest
from helpers import DEMO_DIR, task

from coderepair.backends import load_script, make_backend
from coderepair.benchmark.oracle import OracleBackend
from coderepair.llm.base import BackendError, LLMRequest
from coderepair.llm.ollama_backend import OllamaBackend
from coderepair.llm.scripted import ScriptedBackend
from coderepair.patch import PROPOSAL_JSON_SCHEMA

REQUEST = LLMRequest("system text", "user text", PROPOSAL_JSON_SCHEMA)
PROPOSAL_TEXT = json.dumps({"summary": "fix", "edits": []})


def test_scripted_backend_replays_in_order_and_records_requests():
    backend = ScriptedBackend(["one", "two"])
    assert backend.complete(REQUEST).text == "one"
    assert backend.complete(REQUEST).text == "two"
    assert backend.requests == [REQUEST, REQUEST]
    with pytest.raises(BackendError):
        backend.complete(REQUEST)
    assert backend.is_mock


def test_oracle_backend_replays_gold_and_is_labelled_mock():
    spec = task("t01_paginate_off_by_one")
    response = OracleBackend(spec).complete(REQUEST)
    assert json.loads(response.text) == json.loads(spec.solution_path.read_text())
    assert response.metadata == {"oracle": True}
    assert response.usage_is_estimate


def test_make_backend_errors(settings, tmp_path):
    with pytest.raises(BackendError, match="unknown backend"):
        make_backend("gpt", settings)
    with pytest.raises(BackendError, match="only works for benchmark tasks"):
        make_backend("oracle", settings)
    with pytest.raises(BackendError, match="--script"):
        make_backend("scripted", settings)
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    with pytest.raises(BackendError):
        load_script(bad)


def test_demo_script_loads():
    responses = load_script(DEMO_DIR / "malicious_response.json")
    assert len(responses) == 1 and json.loads(responses[0])["edits"]


# --------------------------------------------------------------------------- ollama


def _ollama(handler) -> OllamaBackend:
    return OllamaBackend("qwen2.5:7b", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_ollama_backend_request_and_response():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:7b",
                "message": {"role": "assistant", "content": PROPOSAL_TEXT},
                "done_reason": "stop",
                "prompt_eval_count": 900,
                "eval_count": 40,
            },
        )

    response = _ollama(handler).complete(REQUEST)
    assert seen["url"] == "http://127.0.0.1:11434/api/chat"
    assert seen["body"]["format"] == PROPOSAL_JSON_SCHEMA
    assert seen["body"]["stream"] is False
    assert seen["body"]["options"]["temperature"] == 0
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]
    assert response.text == PROPOSAL_TEXT
    assert (response.input_tokens, response.output_tokens) == (900, 40)


def test_ollama_backend_errors():
    with pytest.raises(BackendError, match="HTTP 500") as info:
        _ollama(lambda r: httpx.Response(500, text="boom")).complete(REQUEST)
    assert info.value.retryable
    with pytest.raises(BackendError, match="truncated"):
        _ollama(
            lambda r: httpx.Response(
                200, json={"message": {"content": "{"}, "done_reason": "length"}
            )
        ).complete(REQUEST)
    with pytest.raises(BackendError, match="unexpected"):
        _ollama(lambda r: httpx.Response(200, json={"nope": 1})).complete(REQUEST)

    def refuse(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(BackendError, match="cannot reach Ollama"):
        _ollama(refuse).complete(REQUEST)
