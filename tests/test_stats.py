"""Benchmark statistics: Wilson intervals, exact McNemar tests and the pooled report."""

from __future__ import annotations

import json
import math
from dataclasses import asdict

import pytest

from coderepair.benchmark.compare import BenchRow, load_rows, paired, render_report, summarize
from coderepair.benchmark.stats import (
    format_p,
    mcnemar_exact,
    paired_comparisons,
    sign_flip_test,
    wilson_interval,
)


def test_wilson_interval_matches_reference_values():
    # Reference values (Wilson score interval, z = 1.96) from statsmodels' proportion_confint.
    lo, hi = wilson_interval(3, 22)
    assert lo == pytest.approx(0.0475, abs=5e-4) and hi == pytest.approx(0.3333, abs=5e-4)
    lo, hi = wilson_interval(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=5e-4)
    lo, hi = wilson_interval(10, 10)
    assert hi == 1.0 and lo == pytest.approx(0.7225, abs=5e-4)
    assert wilson_interval(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson_interval(5, 4)


def test_mcnemar_exact_is_a_two_sided_sign_test():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(1, 1) == 1.0
    assert mcnemar_exact(0, 2) == 0.5  # 2 * (1/4)
    assert mcnemar_exact(0, 5) == pytest.approx(2 / 32)
    assert mcnemar_exact(1, 9) == pytest.approx(2 * (1 + 10) / 1024)
    assert mcnemar_exact(9, 1) == mcnemar_exact(1, 9)
    assert mcnemar_exact(0, 30) == pytest.approx(2 / 2**30)
    with pytest.raises(ValueError):
        mcnemar_exact(-1, 2)


def test_paired_comparisons_use_only_shared_units():
    outcomes = {
        "a": {"t1": True, "t2": True, "t3": False, "t4": False, "t5": True},
        "b": {"t1": True, "t2": False, "t3": True, "t4": False},  # t5 missing for b
    }
    (c,) = paired_comparisons(outcomes, ["a", "b"])
    assert (c.tasks, c.both, c.only_a, c.only_b, c.neither) == (4, 1, 1, 1, 1)
    assert c.difference == 0 and c.p_value == 1.0


def _row(task_id, agent, resolved, model="m"):
    return BenchRow(
        suite="fixtures", task_id=task_id, agent=agent, backend="ollama", model=model,
        status="resolved" if resolved else "unresolved", resolved=resolved, pass_at_1=False,
        failure="" if resolved else "wrong-fix", calls=1, input_tokens=1, output_tokens=1,
        llm_latency_s=0.0, wall_s=0.0, f2p_passing="", p2p_broken=0, diff_lines=0,
    )  # fmt: skip


def test_summary_and_paired_rows():
    rows = [_row(f"t{i}", "direct", i < 1) for i in range(10)]
    rows += [_row(f"t{i}", "feedback", i < 6) for i in range(10)]
    summary = summarize(rows)
    assert summary["feedback"]["resolve_ci95"] == [round(x, 3) for x in wilson_interval(6, 10)]
    (c,) = paired(rows, ["direct", "feedback"])
    assert (c["only_a"], c["only_b"], c["both"]) == (0, 5, 1)
    assert c["p_value"] == pytest.approx(2 / 32, abs=1e-4)


def _write(path, config, rows):
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps({"config": config, "row": asdict(row)}) + "\n")


def test_load_rows_keeps_the_latest_configuration_and_last_row(tmp_path):
    path = tmp_path / "r.jsonl"
    _write(path, "old", [_row("t1", "direct", True)])
    _write(path, "new", [_row("t1", "direct", False), _row("t2", "direct", False)])
    _write(path, "new", [_row("t2", "direct", True)])
    path.open("a").write('{"config": "new", "row": {"task_id"')  # truncated line
    config, rows = load_rows(path)
    assert config == "new"
    assert [(r.task_id, r.resolved) for r in rows] == [("t1", False), ("t2", True)]


def test_sign_flip_test_reduces_to_mcnemar_and_ignores_duplicated_runs():
    for only_a, only_b in [(0, 2), (1, 9), (3, 3), (0, 7)]:
        diffs = [1] * only_a + [-1] * only_b + [0] * 5
        assert sign_flip_test(diffs) == pytest.approx(mcnemar_exact(only_a, only_b))
    diffs = [1, 1, 1, 0, -1]
    doubled = [2 * d for d in diffs]  # the same file passed twice, pooled by task
    assert sign_flip_test(doubled) == pytest.approx(sign_flip_test(diffs))
    assert sign_flip_test([]) == 1.0 and sign_flip_test([0, 0]) == 1.0
    # [2, 1]: sums over the four sign patterns are 3, 1, -1, -3 -> |s| >= 3 in 2 of 4.
    assert sign_flip_test([2, 1]) == pytest.approx(0.5)
    assert sign_flip_test(iter([1, 1, 1])) == pytest.approx(0.25)  # generators work


def test_format_p():
    assert format_p(0.0004) == "<0.001" and format_p(0.25) == "0.250" and format_p(1.0) == "1.000"


def test_report_pools_runs_by_task(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    # Same task ids in both files (two models on the same tasks).
    _write(a, "c1", [_row(f"t{i}", "direct", False) for i in range(5)])
    _write(a, "c1", [_row(f"t{i}", "feedback", i < 3) for i in range(5)])
    _write(b, "c2", [_row(f"t{i}", "direct", False, "m2") for i in range(5)])
    _write(b, "c2", [_row(f"t{i}", "feedback", i < 4, "m2") for i in range(5)])
    text = render_report([a, b])
    assert "| direct | 0/10 |" in text and "| feedback | 7/10 |" in text
    # Per-task differences (direct - feedback): -2, -2, -2, -1, 0 -> four nonzero tasks.
    p = sign_flip_test([-2, -2, -2, -1, 0])
    assert f"| direct vs feedback | 5 | 10 | -7 | {format_p(p)} |" in text
    assert math.isclose(p, 2 / 16)  # only the all-negative and all-positive patterns reach |7|


def test_report_drops_rows_on_outdated_task_content(tmp_path):
    path = tmp_path / "r.jsonl"
    rows = [_row("t1", "direct", True), _row("t2", "direct", True)]
    rows[0].task_hash, rows[1].task_hash = "current", "old"
    _write(path, "c", rows)
    text = render_report([path], {"t1": "current", "t2": "new"})
    assert "| direct | 1/1 |" in text and "1 rows on outdated task content" in text
