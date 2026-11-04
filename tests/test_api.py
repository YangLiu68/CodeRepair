from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from helpers import task

from coderepair.api import create_app

TASK = "t05_lru_recency"


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings, extra_hosts=("testserver",)))


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
    assert len(tasks) == 44
    assert {t["id"][0] for t in tasks} == {"t", "q", "h"}
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
    hard = client.get("/api/tasks/h07_coupon_counts_invoices")
    assert hard.status_code == 200
    assert "test_hidden_" not in hard.text
    assert "return last is None or period_index" not in hard.text  # a gold-only line


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


def test_state_changing_requests_need_json_from_the_same_origin(client):
    url = f"/api/tasks/{TASK}/proposals"
    cross = client.post(url, json={"backend": "oracle"}, headers={"Origin": "https://evil.example"})
    assert cross.status_code == 403
    form = client.post(url, content="backend=oracle", headers={"Content-Type": "text/plain"})
    assert form.status_code == 415
    loopback = {"Origin": "http://127.0.0.1:8000", "Host": "127.0.0.1:8000"}
    assert client.post(url, json={"backend": "oracle"}, headers=loopback).status_code == 200
    other_port = {"Origin": "http://127.0.0.1:9999", "Host": "127.0.0.1:8000"}
    assert client.post(url, json={"backend": "oracle"}, headers=other_port).status_code == 403
    assert client.post(url, json={"backend": "oracle"}).status_code == 200  # non-browser client


def test_sandbox_and_benchmark_endpoints(client):
    info = client.get("/api/sandbox").json()
    assert {b["name"] for b in info["backends"]} == {"docker", "seatbelt"}
    listing = client.get("/api/benchmarks")
    assert listing.status_code == 200
    assert client.get("/api/benchmarks/..%2F..%2Fetc").status_code == 404
    assert client.get("/api/benchmarks/nope").status_code == 404


def test_repair_and_approval_round_trip(client, sandbox):
    run = client.post(f"/api/tasks/{TASK}/repairs", json={"backend": "oracle", "max_attempts": 1})
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["mode"] == "repair-loop" and body["status"] == "fixed"
    detail = client.get(f"/api/runs/{body['run_id']}").json()
    assert detail["candidate_patches"]["1"] == body["diff"] and detail["approval"] is None
    approval = client.post(f"/api/runs/{body['run_id']}/approval", json={"reviewer": "dana"})
    assert approval.status_code == 200 and approval.json()["reviewer"] == "dana"
    again = client.post(f"/api/runs/{body['run_id']}/approval", json={"reviewer": "eve"})
    assert again.status_code == 409
    assert client.get(f"/api/runs/{body['run_id']}").json()["approval"]["reviewer"] == "dana"
