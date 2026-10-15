# Testing

```bash
uv sync --all-extras
uv run pytest                        # 190 tests; ~25-50 s on an idle Apple M4, slower under load
uv run ruff check . && uv run ruff format --check .
uv run coderepair validate-fixtures  # fixture acceptance check + manifest
uv run coderepair eval-retrieval     # retrieval metrics
```

No API keys, network access, GPU or container runtime are needed. Tests write run
artifacts only to pytest temp directories.

## What the suite covers

| File | Covers |
|---|---|
| `test_security.py` | Sensitive-path rules; repo-root policy (allowed roots, `$HOME` and its parents, denied dirs, symlink resolution); secret redaction; injection scanner true positives on t10 and zero false positives on the other 9 fixture repos |
| `test_repo.py` | Snapshot contents and hash determinism; exclusion of `.env`, keys, binaries, oversized, non-UTF-8, symlinked files and dirs, tool directories; secrets never read; file-count and size limits; `.git/HEAD` parsing incl. malicious refs |
| `test_issue.py` | Traceback frames, exception, test ids, identifiers from inline code / prose / indented blocks, injection flags, CRLF input |
| `test_search.py` | Tokenizer, module names, test-path detection, AST symbol index, import graph, grep (literal, regex, glob, regex cap), line-numbered reads, unparseable files |
| `test_retrieval.py` | Milestone threshold (recall@3 ≥ 0.8, better than random), foreign-path resolution, traceback reasons, multi-file root cause, test-file selection |
| `test_patch.py` | Output parsing (plain, fenced, wrapped, extra fields, malformed); 14 path-policy violations; exact, ambiguous, missing and whitespace-tolerant anchors; degenerate edits; syntax errors; all-or-nothing; sequential edits; size limits; risk flags; EOF newline marker; **`git apply --check` on every gold diff** |
| `test_backends.py` | Scripted and oracle mocks, backend factory errors, Ollama request/response and error handling (httpx mock transport) |
| `test_anthropic_backend.py` | The real `anthropic` SDK against a mock HTTP transport: request shape (model, structured output schema, effort, `fallbacks="default"` + beta header, no sampling params), usage and request id, refusal and `max_tokens` stop reasons, 400/401/429/500 handling |
| `test_agent.py` | Oracle reproduces the gold diff on 10/10 tasks; **no gold-added or hidden-test line reaches any prompt**; trace event sequence and artifacts; source repo unchanged; injection fenced and flagged; malicious output rejected; risky output flagged; closing-tag escaping; secret redaction end to end; parse / no-edit / backend failure statuses |
| `test_fixtures.py` | All 10 fixtures valid (3 pytest runs each); manifest up to date; task-id validation; validator refuses untrusted roots and symlinks and detects a non-fixing gold patch, a wrong fail-to-pass list and hidden tests that miss the bug |
| `test_api.py` | Health and security headers, foreign `Host` rejected, only agent-visible data exposed, retrieval, malicious ids → 404, proposal round trip with stored trace, scripted backend not exposed, no HTML-injection sinks in the viewer script |
| `test_cli.py` | Every command, oracle banner, JSON output, malicious script rejected, allowed-roots enforcement, local repo proposal leaves files untouched |

## Milestone 1 acceptance criteria → evidence

| # | Criterion (PLAN.md) | Evidence |
|---|---|---|
| 1 | 10/10 fixtures valid, manifest matches | `test_fixtures.py::test_fixture_is_valid`, `test_manifest_is_up_to_date`, `coderepair validate-fixtures` |
| 2 | Ingestion policy | `test_security.py`, `test_repo.py` |
| 3 | Issue parsing | `test_issue.py` |
| 4 | Retrieval recall@3 ≥ 0.8, reported | `test_retrieval.py`, `coderepair eval-retrieval` (measured 1.00) |
| 5 | Validation rejects unsafe or invalid edits | `test_patch.py`, `test_agent.py::test_malicious_model_output_is_rejected` |
| 6 | Oracle reproduces gold 10/10 | `test_agent.py::test_oracle_pipeline_reproduces_gold_diff` |
| 7 | No solution leakage into prompts | `test_agent.py::test_prompt_contains_no_solution_or_hidden_test_content`, `test_leakage_check_is_not_vacuous` |
| 8 | Diffs apply with `git apply --check` | `test_patch.py::test_gold_diffs_apply_with_git` |
| 9 | Lint and tests pass locally and in CI | `.github/workflows/ci.yml` |

## The one place code runs on the host

`validate-fixtures` (and `test_fixtures.py`) run each fixture's own pytest suite. This is allowed
only for first-party fixtures under the trusted root `benchmarks/tasks`, on a temp copy, with an
environment containing only `PATH`, `HOME`/`TMPDIR` (a temp dir), locale and Python flags,
third-party pytest plugin autoloading disabled, and a timeout. Per-test outcomes are collected by
a small plugin (`coderepair.benchmark.pytest_results`) instead of parsing console output.
Model-written patches are never executed in M1.

## Not covered by automated tests

- Live Anthropic API calls (no key on the development machine). The SDK integration is tested
  offline against the real SDK with a mock transport.
- Live Ollama calls in CI. A manual local smoke run is recorded in BENCHMARK.md and
  `docs/results/`.
- The browser viewer's behaviour (only served assets and API are tested).

## CI

`.github/workflows/ci.yml` runs on push and pull request with Python 3.11, 3.12 and 3.13: locked
install, ruff lint and format check, pytest, fixture validation, retrieval metrics, and an oracle
smoke run over all tasks. It uses a read-only token, no secrets, and does not persist checkout
credentials. It has not run on GitHub yet because the repository has no remote; the same commands
pass locally.
