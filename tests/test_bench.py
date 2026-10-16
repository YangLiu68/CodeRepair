"""Milestone 5: the comparative benchmark harness (mock backends, real sandbox)."""

from __future__ import annotations

import json

import pytest
from helpers import task

from coderepair.benchmark import compare
from coderepair.benchmark.compare import (
    BenchBudget,
    classify_evaluation,
    classify_invalid,
    run_benchmark,
)
from coderepair.benchmark.oracle import OracleBackend
from coderepair.llm.scripted import ScriptedBackend

T01, T02 = task("t01_paginate_off_by_one"), task("t02_mutable_default_tags")


def _bench(tmp_path, tasks, agents, backend_for, sandbox, **budget):
    return run_benchmark(
        [("fixtures", t) for t in tasks],
        agents,
        backend_for,
        sandbox,
        out_path=tmp_path / "bench.jsonl",
        budget=BenchBudget(**budget),
        progress=lambda _line: None,
    )


def test_oracle_resolves_with_one_call_per_agent(sandbox, tmp_path):
    result = _bench(tmp_path, [T01], ("direct", "retrieval", "feedback"), OracleBackend, sandbox)
    rows = result["rows"]
    assert {r.agent for r in rows} == {"direct", "retrieval", "feedback"}
    assert all(r.resolved and r.pass_at_1 and r.calls == 1 for r in rows)
    assert result["summary"]["feedback"]["resolved"] == 1


def test_every_model_call_is_counted_and_capped(sandbox, tmp_path):
    bad = json.dumps(
        {"summary": "", "edits": [{"path": "pager/core.py", "old": "nope", "new": "x"}]}
    )
    backends = {}

    def backend_for(t):
        return backends.setdefault(t.id, ScriptedBackend([bad] * 10))

    result = _bench(tmp_path, [T01], ("feedback",), backend_for, sandbox, max_calls=3)
    (row,) = result["rows"]
    assert row.calls == 3 == len(backends[T01.id].requests)
    assert row.status == "no-patch" and row.failure == "anchor-mismatch"


def test_sampled_feedback_differs_from_feedback_only_in_sampling(sandbox, tmp_path):
    bad = json.dumps(
        {"summary": "", "edits": [{"path": "pager/core.py", "old": "nope", "new": "x"}]}
    )
    backends = []

    def backend_for(_t):
        backends.append(ScriptedBackend([bad] * 10))
        return backends[-1]

    agents = ("feedback", "feedback-sampled")
    result = _bench(tmp_path, [T01], agents, backend_for, sandbox, max_calls=3)
    assert [r.agent for r in result["rows"]] == list(agents)
    _probe, plain, sampled = backends
    assert [r.sample_index for r in plain.requests] == [0, 0, 0]
    assert [r.sample_index for r in sampled.requests] == [0, 1, 2]
    # Same prompts, including the fed-back validation errors: only the sampling differs.
    assert [r.user for r in plain.requests] == [r.user for r in sampled.requests]
    assert "not found" in plain.requests[1].user


def test_adding_an_agent_reuses_the_other_agents_rows(sandbox, tmp_path):
    _bench(tmp_path, [T01], ("retrieval",), OracleBackend, sandbox)
    calls = []

    def counting(t):
        calls.append(t.id)
        return OracleBackend(t)

    result = _bench(tmp_path, [T01], ("retrieval", "direct"), counting, sandbox)
    assert len(calls) == 2  # the metadata probe and the new agent; retrieval was reused
    assert sorted(r.agent for r in result["rows"]) == ["direct", "retrieval"]


def test_resume_reuses_only_matching_rows_and_survives_truncation(sandbox, tmp_path):
    first = _bench(tmp_path, [T01, T02], ("retrieval",), OracleBackend, sandbox)
    assert len(first["rows"]) == 2
    path = tmp_path / "bench.jsonl"
    with path.open("a") as fh:
        fh.write('{"config": "trunc')  # an interrupted write
    calls = []

    def counting(t):
        calls.append(t.id)
        return OracleBackend(t)

    again = _bench(tmp_path, [T01], ("retrieval",), counting, sandbox)
    assert [r.task_id for r in again["rows"]] == [T01.id]  # T02 not reported for this selection
    assert calls == [T01.id]  # only the probe for metadata; the row itself was reused
    assert again["summary"]["retrieval"]["tasks"] == 1


def test_changed_task_content_invalidates_resumed_rows(sandbox, tmp_path, monkeypatch):
    _bench(tmp_path, [T01], ("direct",), OracleBackend, sandbox)
    monkeypatch.setattr(compare, "task_hash", lambda t: "different")
    calls = []

    def counting(t):
        calls.append(t.id)
        return OracleBackend(t)

    _bench(tmp_path, [T01], ("direct",), counting, sandbox)
    assert len(calls) == 2  # metadata probe + a fresh run


def test_a_crashing_row_does_not_end_the_run(sandbox, tmp_path, monkeypatch):
    real = compare.run_agent

    def flaky(agent, t, *args, **kwargs):
        if t.id == T01.id:
            raise RuntimeError("boom")
        return real(agent, t, *args, **kwargs)

    monkeypatch.setattr(compare, "run_agent", flaky)
    result = _bench(tmp_path, [T01, T02], ("direct",), OracleBackend, sandbox)
    by_task = {r.task_id: r for r in result["rows"]}
    assert by_task[T01.id].failure == "harness-error" and "boom" in by_task[T01.id].detail
    assert by_task[T02.id].resolved


@pytest.mark.parametrize(
    "errors, category",
    [
        (["edit 0 (a.py): 'old' text not found in the file"], "anchor-mismatch"),
        (["a.py: edit produces invalid Python (line 3: x)"], "syntax-error"),
        (["could not parse proposal: invalid JSON"], "invalid-output"),
        (["model proposed no edits"], "no-edits"),
        (["edit 0 (tests/t.py): protected path (tests may not be modified)"], "policy-violation"),
        (["backend error: timeout"], "backend-error"),
        (["sandbox error: baseline test run failed to start"], "sandbox-error"),
    ],
)
def test_failure_categories(errors, category):
    assert classify_invalid(errors) == category


def test_evaluation_categories():
    from coderepair.benchmark.evaluate import PatchEvaluation

    assert classify_evaluation(PatchEvaluation("t", "resolved")) == ""
    wrong = PatchEvaluation("t", "unresolved", fail_to_pass={"a": "failed"})
    assert classify_evaluation(wrong) == "wrong-fix"
    regress = PatchEvaluation(
        "t", "unresolved", fail_to_pass={"a": "passed"}, pass_to_pass_broken={"b": "failed"}
    )
    assert classify_evaluation(regress) == "regression"
