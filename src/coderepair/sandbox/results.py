"""Parse the per-test results file written inside the sandbox.

The file is produced by a pytest plugin that runs in the same process as the
code under test, so it is untrusted input: its size, shape and contents are
bounded and validated here, and a per-run nonce rejects stale or missing files.
The nonce does not stop deliberately forged results from adversarial code that
reads its own environment; see ARCHITECTURE.md ("Trust in test outcomes").
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

MAX_RESULTS_BYTES = 2_000_000
MAX_TESTS = 5_000
MAX_NODEID_CHARS = 1_000
OUTCOMES = frozenset({"passed", "failed", "error", "skipped"})


@dataclass(frozen=True)
class TestResults:
    __test__ = False  # not a pytest test class

    outcomes: dict[str, str]
    collect_errors: tuple[str, ...]
    exitstatus: int

    def ids_with(self, outcome: str) -> list[str]:
        return sorted(t for t, o in self.outcomes.items() if o == outcome)

    @property
    def all_passed(self) -> bool:
        """Green: no collection errors, nothing failed or errored, at least one test passed.

        Skipped tests are allowed (platform skips, missing optional dependencies).
        """
        values = self.outcomes.values()
        return (
            not self.collect_errors
            and any(o == "passed" for o in values)
            and not any(o in ("failed", "error") for o in values)
        )

    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys(sorted(OUTCOMES), 0)
        for outcome in self.outcomes.values():
            counts[outcome] += 1
        return counts

    def to_dict(self) -> dict:
        return {
            "counts": self.counts(),
            "collect_errors": list(self.collect_errors),
            "exitstatus": self.exitstatus,
            "tests": dict(sorted(self.outcomes.items())),
        }


class ResultsError(ValueError):
    pass


def read_results_file(path: Path, nonce: str) -> TestResults:
    """Read and validate a results file without following symlinks.

    ``O_NONBLOCK`` keeps a FIFO planted at the results path from blocking the
    open; the ``fstat`` check then rejects anything that is not a regular file.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError as exc:
        raise ResultsError("no results file was written (session crashed or exited early)") from exc
    except OSError as exc:
        raise ResultsError(f"results file could not be opened safely: {exc.strerror}") from exc
    with os.fdopen(fd, "rb") as fh:
        info = os.fstat(fh.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ResultsError("results path is not a regular file")
        data = fh.read(MAX_RESULTS_BYTES + 1)
    if len(data) > MAX_RESULTS_BYTES:
        raise ResultsError(f"results file larger than {MAX_RESULTS_BYTES} bytes")
    return parse_results(data, nonce)


def parse_results(data: bytes, nonce: str) -> TestResults:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError) as exc:  # includes huge-integer conversion limits
        raise ResultsError(f"results file is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ResultsError("results file must contain a JSON object")
    if payload.get("nonce") != nonce:
        raise ResultsError("results nonce mismatch (stale or forged results file)")
    tests = payload.get("tests")
    errors = payload.get("collect_errors")
    exitstatus = payload.get("exitstatus")
    if not isinstance(tests, dict) or not isinstance(errors, list):
        raise ResultsError("results file has the wrong shape")
    if not isinstance(exitstatus, int) or isinstance(exitstatus, bool):
        raise ResultsError("exitstatus must be an integer")
    if len(tests) > MAX_TESTS or len(errors) > MAX_TESTS:
        raise ResultsError(f"more than {MAX_TESTS} entries in results file")
    outcomes: dict[str, str] = {}
    for nodeid, outcome in tests.items():
        if not isinstance(outcome, str) or outcome not in OUTCOMES:
            raise ResultsError(f"unknown outcome {str(outcome)[:40]!r}")
        if len(nodeid) > MAX_NODEID_CHARS or any(ord(c) < 32 for c in nodeid):
            raise ResultsError("invalid test id in results file")
        outcomes[nodeid] = outcome
    collect_errors = []
    for item in errors:
        if not isinstance(item, str) or len(item) > MAX_NODEID_CHARS:
            raise ResultsError("invalid collection error entry")
        collect_errors.append(item)
    return TestResults(outcomes, tuple(collect_errors), exitstatus)
