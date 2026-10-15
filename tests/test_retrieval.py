from __future__ import annotations

from helpers import TASKS_DIR, snapshot_of, task

from coderepair.benchmark.retrieval_eval import evaluate_retrieval
from coderepair.benchmark.tasks import list_tasks
from coderepair.issue import parse_issue
from coderepair.retrieval import rank_files, rank_test_files, resolve_mention, source_ranking
from coderepair.search import RepoIndex


def _rank(task_id: str):
    snapshot = snapshot_of(task_id)
    index = RepoIndex(snapshot)
    issue = parse_issue(task(task_id).read_issue())
    return rank_files(snapshot, index, issue), issue, index


def test_retrieval_meets_milestone_threshold_and_beats_random():
    result = evaluate_retrieval(list_tasks(TASKS_DIR), (TASKS_DIR,))
    agg = result["aggregate"]
    assert agg["tasks"] == 10
    assert agg["recall@3"] >= 0.8
    assert agg["recall@1"] > agg["random_recall@1"]
    assert agg["mrr"] >= 0.8


def test_resolve_mention_maps_foreign_absolute_paths():
    paths = ["timefmt/__init__.py", "timefmt/duration.py", "tests/test_duration.py"]
    assert resolve_mention("/home/dev/src/timefmt/timefmt/duration.py", paths) == [
        "timefmt/duration.py"
    ]
    assert resolve_mention("duration.py", paths) == ["timefmt/duration.py"]
    assert resolve_mention("__init__.py", ["a/__init__.py", "b/__init__.py"]) == []
    assert resolve_mention("other.py", paths) == []


def test_traceback_frame_is_a_reason():
    ranked, _, _ = _rank("t04_duration_whitespace")
    top = source_ranking(ranked)[0]
    assert top.path == "timefmt/duration.py"
    assert any(reason.startswith("traceback frame (line 22)") for reason in top.reasons)


def test_multifile_bug_reaches_root_cause_through_imports():
    ranked, _, _ = _rank("t06_coupon_threshold_multifile")
    sources = [r.path for r in source_ranking(ranked)]
    assert "shop/coupons.py" in sources[:2]
    coupons = next(r for r in ranked if r.path == "shop/coupons.py")
    assert any("imported by failing test tests/test_cart.py" in r for r in coupons.reasons)


def test_relevant_tests_are_selected_even_without_lexical_overlap():
    ranked, issue, index = _rank("t09_slugify_accents")
    assert [r.path for r in rank_test_files(ranked, issue, index)][:1] == ["tests/test_slug.py"]


def test_named_failing_test_comes_first():
    ranked, issue, index = _rank("t05_lru_recency")
    assert rank_test_files(ranked, issue, index)[0].path == "tests/test_lru.py"
