"""Smoke run: one proposal per benchmark task with a given backend.

This is NOT a benchmark. Milestone 1 never executes model-written code, so a
"proposed" patch here has only passed static validation; whether it fixes the
bug is unknown until the Milestone 2 sandbox runs the tests. The only
correctness signal reported is an exact match with the gold diff.

Usage: uv run python scripts/smoke_run.py --backend ollama [--out results.json]
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections import Counter
from datetime import UTC, datetime

from coderepair.agent import propose_patch
from coderepair.backends import BACKEND_NAMES, make_backend
from coderepair.benchmark.tasks import list_tasks
from coderepair.config import Settings
from coderepair.repo import ingest_repository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", choices=BACKEND_NAMES, required=True)
    parser.add_argument("--out", help="write results JSON here")
    args = parser.parse_args()

    settings = Settings.from_env()
    rows = []
    for task in list_tasks(settings.tasks_dir):
        snapshot = ingest_repository(task.repo_dir, settings.allowed_roots, settings.limits)
        backend = make_backend(args.backend, settings, task=task)
        run = propose_patch(
            snapshot,
            task.read_issue(),
            backend,
            limits=settings.limits,
            runs_dir=settings.runs_dir,
            task_id=task.id,
        )
        gold = task.solution_patch_path.read_text(encoding="utf-8")
        row = {
            "task_id": task.id,
            "status": run.status,
            "exact_gold_match": bool(run.diff) and run.diff == gold,
            "files_changed": sorted(run.patch.changed_files) if run.patch and run.patch.ok else [],
            "errors": run.errors,
            "input_tokens": run.response.input_tokens if run.response else None,
            "output_tokens": run.response.output_tokens if run.response else None,
            "llm_latency_s": round(run.response.latency_s, 2) if run.response else None,
            "run_id": run.run_id,
        }
        rows.append(row)
        print(
            f"{task.id:<34} {run.status:<13} gold-match={row['exact_gold_match']!s:<5} "
            f"latency={row['llm_latency_s']}s  {'; '.join(run.errors)[:120]}",
            flush=True,
        )

    result = {
        "kind": "smoke-run (not a benchmark; patches were not executed)",
        "backend": args.backend,
        "model": make_backend(args.backend, settings, task=list_tasks(settings.tasks_dir)[0]).model,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": f"{platform.system()} {platform.machine()} / Python {platform.python_version()}",
        "tasks": rows,
        "counts": dict(Counter(r["status"] for r in rows)),
        "exact_gold_matches": sum(r["exact_gold_match"] for r in rows),
    }
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
            fh.write("\n")
    print(json.dumps({k: result[k] for k in ("counts", "exact_gold_matches")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
