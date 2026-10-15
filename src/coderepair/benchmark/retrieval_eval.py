"""Measure how well retrieval finds the files the gold patch edits."""

from __future__ import annotations

from pathlib import Path

from ..issue import parse_issue
from ..repo import ingest_repository
from ..retrieval import rank_files, source_ranking
from ..search import RepoIndex, is_test_path
from .tasks import TaskSpec


def evaluate_retrieval(
    tasks: list[TaskSpec], allowed_roots: tuple[Path, ...], ks: tuple[int, ...] = (1, 3, 5)
) -> dict:
    rows = []
    for task in tasks:
        snapshot = ingest_repository(task.repo_dir, allowed_roots)
        issue = parse_issue(task.read_issue())
        ranking = [r.path for r in source_ranking(rank_files(snapshot, RepoIndex(snapshot), issue))]
        gold = sorted({edit.path for edit in task.load_solution().edits})
        ranks = {g: (ranking.index(g) + 1 if g in ranking else None) for g in gold}
        found = [r for r in ranks.values() if r is not None]
        # Expected recall of a uniformly random ordering of all non-test files (context baseline).
        n_candidates = sum(1 for p in snapshot.paths() if not is_test_path(p))
        rows.append(
            {
                "task_id": task.id,
                "gold_files": gold,
                "gold_ranks": ranks,
                "candidates": n_candidates,
                "top_5": ranking[:5],
                **{f"recall@{k}": sum(1 for r in found if r <= k) / len(gold) for k in ks},
                **{f"random_recall@{k}": min(k, n_candidates) / n_candidates for k in ks},
                "reciprocal_rank": 1 / min(found) if found else 0.0,
            }
        )
    n = len(rows) or 1
    aggregate = {f"recall@{k}": sum(r[f"recall@{k}"] for r in rows) / n for k in ks}
    aggregate.update(
        {f"random_recall@{k}": sum(r[f"random_recall@{k}"] for r in rows) / n for k in ks}
    )
    aggregate["mrr"] = sum(r["reciprocal_rank"] for r in rows) / n
    aggregate["tasks"] = len(rows)
    return {"aggregate": aggregate, "tasks": rows}
