"""Pytest plugin that records the outcome of every test node id as JSON.

Loaded with ``-p coderepair.benchmark.pytest_results``; writes to the file named by
``CODEREPAIR_RESULTS_PATH``. Outcomes: passed, failed, error (setup/teardown or
collection failure), skipped.
"""

from __future__ import annotations

import json
import os

_SEVERITY = {"passed": 0, "skipped": 1, "failed": 2, "error": 3}
_results: dict[str, str] = {}
_collect_errors: list[str] = []


def _record(nodeid: str, outcome: str) -> None:
    previous = _results.get(nodeid)
    if previous is None or _SEVERITY[outcome] > _SEVERITY[previous]:
        _results[nodeid] = outcome


def pytest_runtest_logreport(report) -> None:
    if report.when == "call":
        _record(report.nodeid, report.outcome)
    elif report.failed:
        _record(report.nodeid, "error")
    elif report.skipped:
        _record(report.nodeid, "skipped")


def pytest_collectreport(report) -> None:
    if report.failed:
        _collect_errors.append(report.nodeid or "<session>")


def pytest_sessionfinish(session, exitstatus) -> None:
    path = os.environ.get("CODEREPAIR_RESULTS_PATH")
    if not path:
        return
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {"tests": _results, "collect_errors": _collect_errors, "exitstatus": int(exitstatus)},
            fh,
            indent=2,
            sort_keys=True,
        )
