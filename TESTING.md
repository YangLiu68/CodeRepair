# Testing

```bash
uv sync --all-extras
uv run pytest -rs                    # unit, security, sandbox, loop, review, API and acceptance tests
uv run ruff check . && uv run ruff format --check .
uv run coderepair sandbox selftest   # 15 abuse probes against the sandbox in use
uv run coderepair validate-fixtures --suite all   # fixtures (host) + public subset (sandboxed)
uv run coderepair eval-retrieval     # retrieval metrics on the fixtures
```

No API keys, network access or GPU are needed. Tests that execute code take a `sandbox` argument
and run once per backend: on macOS the Seatbelt backend runs and the Docker variants are reported
as skipped with the reason ("docker CLI not found"); on the CI runners Docker runs. Nothing is ever
executed outside a sandbox to make a test pass. Run artifacts go to pytest temp directories.

## What the suite covers

| File | Covers |
|---|---|
| `test_security.py` | Sensitive-path rules; repo-root policy; secret redaction; injection scanner true positives on t10 and zero false positives on the other fixtures |
| `test_repo.py` | Snapshot contents and hashes; exclusion of secrets, binaries, oversized, non-UTF-8, symlinked files; limits; `.git/HEAD` parsing |
| `test_issue.py`, `test_search.py`, `test_retrieval.py` | Issue hints, search, retrieval threshold (recall@3 ≥ 0.8), multi-file root cause |
| `test_patch.py` | Output parsing, 14 path-policy violations, anchors, syntax errors, all-or-nothing, size limits, risk flags, `git apply --check` on every gold diff |
| `test_backends.py`, `test_anthropic_backend.py` | Mocks, Ollama and the real Anthropic SDK against mock HTTP transports |
| `test_agent.py` | Oracle reproduces 10/10 gold diffs; no gold-added or hidden-test line in any prompt; traces; injection fencing; malicious output rejected |
| `test_fixtures.py` | All fixtures valid (host); manifest; pass-to-pass lists; validator refuses untrusted roots and symlinks and detects broken tasks |
| **`test_sandbox.py`** (M2) | Results parsing (nonce, shape, size, symlink, FIFO, huge integers, skips); workspace safety; runner bundle; the exact Seatbelt profile and `docker run` command; factory never falls back to the host; process monitor (deadline, output cap, child killed when the monitor fails, control characters stripped); **every abuse probe contained**; **negative controls** (probes report escapes when isolation is removed, and the process-info probe catches the pre-review profile); fixtures behave identically in the sandbox; gold patches resolve and buggy repos do not for all 10 tasks; a plausible wrong patch is caught by a pass-to-pass test |
| **`test_loop.py`** (M3) | Recovery from a bad anchor and a failing patch; targeted-then-full test selection; budget exhaustion keeps the best candidate; duplicate patches not re-tested; token budget; backend errors; unverified status without a reproducing test; vanished tests do not count as fixed; injection and closing tags in test output and test ids are escaped and redacted; hidden tests never in prompts |
| **`test_review.py`** (M4) | Lint/type deltas report only new diagnostics, never execute code, and report missing tools as skipped; 11 security-review rules; reproduction-test policy; reproduction test verifies an issue-only task and re-ranks candidates; approval and apply (hash check, changed repository, tampered candidate, path policy, protected fixture roots, mandatory risk acknowledgement, approvals are final); CLI review/approve/apply. Review regressions: a planted `mypy.py`/`typing_extensions.py`/`sitecustomize.py` never runs; hidden/bidi characters flagged and escaped; writes never follow symlinked directories; approvals bound to repository and reproduction test; inode-based protected roots; no uncounted model calls; passing candidates survive the scoring cap; skipped baseline tests are not failures; sandbox errors stay per candidate; deeply nested model output |
| **`test_bench.py`** (M5) | Every model call is counted and capped; resume reuses only rows for the same configuration, unchanged task content and the requested (task, agent) pairs, and survives a truncated line; a crashing row is recorded as `harness-error` without ending the run; failure categories |
| **`test_public.py`** (M6) | Size, license and provenance of the public subset; manifest; no upstream traces or gold lines in agent-visible material and prompts; **no issue quotes a hidden test case**; every public task valid in the sandbox; the public suite never runs on the host |
| `test_api.py` | Security headers, `Host` check, **cross-origin and non-JSON POSTs refused**, agent-visible data only, proposals, repairs and approvals over HTTP, sandbox and benchmark endpoints, no HTML sinks in the dashboard script |
| `test_cli.py` | Every command, oracle banner, JSON output, allowed-roots enforcement |

## Acceptance criteria → evidence

| Milestone | Criterion | Evidence |
|---|---|---|
| M1 | Fixtures valid, ingestion policy, issue parsing, retrieval ≥ 0.8 recall@3, validation, oracle 10/10, no leakage, `git apply` | see the M1 rows above; `validate-fixtures`, `eval-retrieval` |
| M2 | Disposable sandbox with no network, non-root, limits, read-only mounts, no secrets; escape and abuse fixtures contained | `test_sandbox.py` probe tests, `coderepair sandbox selftest` (Seatbelt locally, Docker in CI) |
| M3 | Inspect → patch → targeted tests → retry, bounded, traced | `test_loop.py`; `runs/<id>/trace.jsonl` |
| M4 | Candidates, ranking, regression (reproduction) tests, lint/typecheck, security checks, human approval | `test_review.py`; `coderepair review/approve/apply` |
| M5 | Comparative benchmark under equal budgets | `coderepair bench`; `docs/results/m5_*`; BENCHMARK.md |
| M6 | Licensed public subset without leakage | `test_public.py`; LICENSE_NOTES.md |
| M7 | Dashboard, CI, threat model, docs | `test_api.py`; `.github/workflows/ci.yml`; ARCHITECTURE.md |

## Where code runs on the host

1. `validate-fixtures --suite fixtures` without `--sandbox` runs the **first-party** fixtures' tests on
   a temp copy with a scrubbed environment (trusted code, written for this project).
2. Lint and type checks (`ruff`, `mypy`) *analyse* candidate code on the host. Neither tool imports or
   executes it, and repository configuration is ignored (`test_checks_never_execute_repository_code`).

Everything else (public tasks, model-written patches, reproduction tests, abuse probes) runs only in
a sandbox.

## Not covered by automated tests

- **The Docker backend has not been executed on the development machine** (no container runtime).
  Its command line is unit-tested and CI runs the full sandbox suite in Docker, but CI has not run
  yet because the repository has no remote.
- Live Anthropic API calls (no key). The SDK integration is tested offline.
- The dashboard's rendering in a browser (the API and served assets are tested).
- Model quality: real-model numbers come from the recorded benchmark runs in `docs/results/`, not
  from the test suite.
