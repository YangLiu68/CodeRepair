from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from helpers import task

from coderepair.api import create_app

TASK = "t05_lru_recency"


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


def test_health_and_security_headers(client):
    response = client.get("/api/health")
    assert response.status_code == 200 and response.json()["status"] == "ok"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_untrusted_host_header_is_rejected(client):
    response = client.get("/api/health", headers={"host": "attacker.example"})
    assert response.status_code == 400


def test_task_list_and_detail_expose_only_agent_visible_data(client):
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 10
    detail = client.get(f"/api/tasks/{TASK}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["files"] == [
        "cachekit/__init__.py",
        "cachekit/decorators.py",
        "cachekit/lru.py",
        "pyproject.toml",
        "tests/test_lru.py",
    ]
    assert "fail_to_pass" not in body and "solution" not in body
    text = detail.text
    assert "test_hidden_" not in text
    assert "self._data.move_to_end(key)\\n        return value" not in text


def test_retrieval_endpoint(client):
    ranking = client.get(f"/api/tasks/{TASK}/retrieval").json()
    sources = [r["path"] for r in ranking if not r["is_test"]]
    assert sources[0] == "cachekit/lru.py"


def test_unknown_or_malicious_ids_are_404(client):
    assert client.get("/api/tasks/t99_missing").status_code == 404
    assert client.get("/api/tasks/..%2F..%2Fetc").status_code == 404
    assert client.get("/api/runs/..%2F..%2Fetc").status_code == 404
    assert client.get("/api/runs/20990101T000000Z-x-abcdef").status_code == 404


def test_proposal_roundtrip(client, settings):
    response = client.post(f"/api/tasks/{TASK}/proposals", json={"backend": "oracle"})
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "proposed" and run["is_mock"] is True
    assert run["diff"] == task(TASK).solution_patch_path.read_text()
    runs = client.get("/api/runs").json()
    assert [r["run_id"] for r in runs] == [run["run_id"]]
    detail = client.get(f"/api/runs/{run['run_id']}").json()
    assert detail["diff"] == run["diff"]
    assert detail["trace"][0]["kind"] == "start"
    assert (settings.runs_dir / run["run_id"] / "trace.jsonl").is_file()


def test_scripted_backend_is_not_exposed_over_http(client):
    assert (
        client.post(f"/api/tasks/{TASK}/proposals", json={"backend": "scripted"}).status_code == 422
    )


def test_viewer_is_served(client):
    page = client.get("/")
    assert page.status_code == 200 and "CodeRepair" in page.text
    script = client.get("/static/app.js")
    assert script.status_code == 200
    for sink in (".innerHTML", ".outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in script.text
