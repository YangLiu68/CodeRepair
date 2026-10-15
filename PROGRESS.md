# Progress log

## 2026-10-15 — Milestone 5: comparative benchmark run

**What ran:** `coderepair bench --suite all --backend ollama` with `qwen2.5:3b` (the shared
machine's resource manager asks for models of 3B or less), 22 tasks × 3 agents = 66 rows, at most
3 model calls per agent per task, Seatbelt sandbox. Paused once at the resource manager's request
(SIGINT to the benchmark's own process, model unloaded) and resumed from the JSONL; 53 + 13 rows,
one configuration fingerprint. About 35 minutes of compute, 34 of them waiting on the model.

| Agent | Resolved | pass@1 | Valid patch | Tokens |
|---|---|---|---|---|
| direct | 1/22 | 0/22 | 11/22 | 72k |
| retrieval | 3/22 | 2/22 | 14/22 | 72k |
| feedback | 3/22 | 2/22 | 17/22 | 98k |

Findings, stated with their limits in BENCHMARK.md: the 3B model resolves at most 3/22 with any
agent, so the run cannot rank retrieval against feedback; retrieval context and the loop's anchor
hints cut anchor-mismatch failures from 8 to 6 to 2 and raise valid patches from 11 to 17, but the
extra patches were mostly wrong fixes; feedback costs about 36% more tokens.

**Files:** `docs/results/m5_ollama_qwen2.5-3b.{jsonl,summary.json,md}`, BENCHMARK.md, README.md,
dashboard screenshots in `docs/images/`.

**Next steps (not done):** run the same harness with a stronger model (`--backend anthropic` needs
an API key) and several seeds; install Docker or Colima so the container backend is exercised
locally; push to a remote so CI runs; choose a project license.

## 2026-10-15 — Milestones 2–4, 6 and 7

**Scope delivered:** sandboxed test execution (Docker backend + macOS Seatbelt fallback) with 15
abuse probes; the iterative repair loop; candidate sampling, model-written reproduction tests,
lint/type deltas, AST security review, ranking, approval and verified write-back; 12 public tasks
derived from QuixBugs; the comparative benchmark harness; a dashboard; CI with a real Docker job;
updated threat model and docs. M5 results: see the next entry.

### Implemented

| Area | Files |
|---|---|
| Sandbox (M2) | `src/coderepair/sandbox/{base,results,workspace,bundle,process,common,seatbelt,docker,factory,probes}.py`, `execution.py` |
| Repair loop (M3) | `src/coderepair/loop.py`, `agent.py` refactor (`build_context`, `attempt_proposal`) |
| Ranking and approval (M4) | `src/coderepair/{candidates,checks,approval}.py`, CLI `repair --candidates/--repro-test`, `review`, `approve`, `apply` |
| Evaluation and benchmark (M5) | `benchmark/{evaluate,compare}.py`, `prompting.build_direct_prompt`, CLI `evaluate`, `bench`; `pass_to_pass` lists in every `task.toml` |
| Public subset (M6) | `scripts/build_public_subset.py`, `benchmarks/public/` (12 tasks, license, manifest) |
| Dashboard and CI (M7) | `api.py` (repairs, approvals, sandbox, benchmarks, CSRF guard), `static/`, `.github/workflows/ci.yml` |
| Tests | `tests/test_{sandbox,loop,review,public}.py`, updates to `test_api.py`, `test_cli.py`, `conftest.py` |

### Verification (run locally on macOS, Seatbelt backend)

| Command | Result |
|---|---|
| `uv run pytest -rfE` | 344 passed, 65 skipped (the skips are the Docker variants: no Docker on this machine) |
| `uv run coderepair sandbox selftest` | 15/15 probes contained |
| `uv run coderepair validate-fixtures --suite public` | 12/12 public tasks valid (sandboxed), manifest up to date |
| `uv run coderepair validate-fixtures --sandbox seatbelt` | 10/10 fixtures valid inside the sandbox |
| `uv run ruff check .` / `ruff format --check .` / `uv lock --check` | clean |
| Demo scripts in `docs/demo/` | outputs in docs/DEMO.md are from these runs |

Not verified: the Docker backend has never executed here (no container runtime); its command line
is unit-tested and the CI workflow runs the whole sandbox suite in Docker, but CI has not run because
the repository has no remote.

### Problems found and fixed

An independent read-only review of the M2/M3 code found ten issues; all are fixed with regression
tests:

- **Other processes' secrets were readable from the Seatbelt sandbox.** `(deny default)` does not
  cover `process-info` on macOS 15, so `sysctl(KERN_PROCARGS2)` returned the arguments and
  environment of any same-user process, including the harness itself. Fixed with
  `(deny process-info*)` plus `(allow process-info* (target self))` (libinfo needs it inside
  `getaddrinfo`), and a sysctl allowlist. New `process-info` probe, plus a negative control that
  fails on the old profile.
- A FIFO planted at the results path hung the harness; a huge JSON integer crashed it. Results are
  now opened with `O_NONBLOCK` and any `ValueError` is a rejected file.
- Test ids, problems and file excerpts reached the model's feedback unescaped. Everything dynamic
  in feedback is now redacted, tag-escaped and scanned.
- Skipped tests counted as failures, so the loop could never pass on repos with platform skips; and
  "fixed" did not check that the baseline failures actually passed (a patch could make them vanish).
- Disk limits could be bypassed (Docker `/out` had no cap; deleted-but-open files were invisible to
  the scratch scan). Added an output-directory watchdog for Docker and a cumulative disk-write cap
  from `proc_pid_rusage` for Seatbelt.
- The child process could outlive a monitor error; the container user could not read the 0700
  workspace (now runs as the invoking uid); the Seatbelt read scope included the whole Python prefix;
  the sandboxed fixture validator accepted sessions that had hit limits.

Also found while building: the negative-control probe initially passed even when it read the secret,
because a successful attack only printed; `leak()` now fails the test.

A second independent review (M4–M7 code) found 13 more; all fixed with regression tests before
the benchmark was run:

- **Host code execution through the type check:** `python -m mypy` ran in the copied repository,
  and `-m` puts the working directory first on `sys.path`, so a repository `mypy.py` executed on
  the host. Now `python -I -m mypy`.
- **Display tricks:** terminal escape sequences or bidi overrides in a patch could erase the
  security warning from the terminal or reorder code in the dashboard. Both views now escape them,
  and the security review flags them as high severity.
- **Write-back hardening:** `apply` could write through a symlinked parent directory and had a
  check-then-write race; protected roots were compared by spelling (case-insensitive macOS); the
  approval did not cover the reproduction test or bind to the repository. Writes now go through
  `O_NOFOLLOW` directory handles with a final content check, comparisons use inodes, both benchmark
  suites are protected, and approvals pin repository, snapshot hash and reproduction-test hash.
- **Benchmark validity:** the feedback agent could make one uncounted extra call; resumed runs could
  mix rows from other selections or configurations; two public issues quoted hidden test cases (the
  subset was rebuilt; see BENCHMARK.md); a passing attempt could be cut by the scoring cap; sandbox
  errors were labelled as bad patches; deeply nested model output could crash a whole run; skipped
  baseline tests blocked "fixed"; extra samples and static checks ignored the time budget.
- The dashboard trusted the `testserver` host name in production.

### Remaining risks

- Seatbelt shares the host kernel and `sandbox-exec` is deprecated; Docker is the stronger backend.
- In-sandbox results can be forged by code that reads its own nonce (documented; approval is the
  backstop).
- The security review and injection scanner are heuristics.
- The approval gate trusts the local reviewer; there is no authentication on the dashboard.

## 2026-10-14 — Milestone 1 complete

**Scope delivered:** 10 seeded-bug fixture repos, read-only ingestion, issue parsing, read-only code
search, retrieval with reasons, patch proposal through mock and real backends, patch validation,
diff display (CLI, saved artifacts, local web viewer), run traces, docs and CI.

### Implemented

| Area | Files |
|---|---|
| Fixtures | `benchmarks/tasks/t01…t10/` (repo, issue, hidden tests, gold edits, generated gold diff), `benchmarks/manifest.json` |
| Core | `src/coderepair/{config,security,repo,issue,search,retrieval,prompting,patch,trace,agent,backends}.py` |
| Backends | `src/coderepair/llm/{base,scripted,anthropic_backend,ollama_backend}.py`, `src/coderepair/benchmark/oracle.py` |
| Harness | `src/coderepair/benchmark/{tasks,validate,pytest_results,manifest,retrieval_eval}.py`, `scripts/smoke_run.py` |
| Interfaces | `src/coderepair/cli.py`, `src/coderepair/api.py`, `src/coderepair/static/` |
| Tests | `tests/` (12 modules, 190 tests) |
| Docs and ops | `PLAN.md`, `README.md`, `ARCHITECTURE.md`, `TESTING.md`, `BENCHMARK.md`, `LICENSE_NOTES.md`, `docs/DEMO.md`, `.env.example`, `.github/workflows/ci.yml`, `.gitattributes` |

### Verification (run locally, 2026-10-14)

| Command | Result |
|---|---|
| `uv run pytest` | 190 passed |
| `uv run ruff check .` / `uv run ruff format --check .` | clean |
| `uv run coderepair validate-fixtures` | 10/10 fixtures valid, manifest up to date |
| `uv run coderepair eval-retrieval` | recall@1 0.90, recall@3 1.00, MRR 0.95 (random recall@1 0.26) |
| `uv lock --check` | lockfile current |
| `coderepair serve` + curl | health OK, CSP present, oracle proposal OK, foreign `Host` → 400 |
| `scripts/smoke_run.py --backend ollama` (qwen2.5:7b) | 6/10 passed static validation, 1/10 identical to gold; patches not executed |

All nine M1 acceptance criteria in PLAN.md are met; the mapping to tests is in TESTING.md.
GitHub Actions has not run because the repository has no remote yet.

### Problems found and fixed during M1

- **Validator early return:** a stale or missing `solution.patch` made `validate_task` skip the
  test-outcome checks. It now stops early only on collection errors. Found by a negative test.
- **Test files missing from context:** for issue-only tasks with no lexical overlap (t09), no test
  file reached the prompt. Tests that import the top-ranked source module are now always eligible.
- **Weak test oracle in t08:** the local model's wrong `+ 0.5` rounding patch would have passed every
  test. Added a hidden pass-to-pass test; documented as a fixture revision in BENCHMARK.md.

### Remaining risks

- **No container runtime on this machine**, so M2 cannot start. There is deliberately no host fallback
  for untrusted code.
- The Anthropic backend is tested offline against the real SDK with a mock transport, but has not made
  a live call (no API key here).
- Injection detection and secret redaction are regex heuristics: useful flags, not guarantees. The
  structural defences (no execution, path policy, protected files, human review) are the actual controls.
- The fixtures are small and written by the same author as the retriever, so retrieval numbers are
  optimistic.
- The local API has no authentication; it is meant for localhost only.

### Next step

Milestone 2, the sandboxed test runner. It needs a container runtime installed first (for example
Colima or Docker Desktop). Then: a disposable container per run with `--network none`, a non-root
user, CPU/memory/pids/time limits, a read-only root filesystem and repository mount, a tmpfs
workspace, no host environment or Docker socket, and untrusted-result parsing with size limits. The
first deliverable will be a suite of escape and abuse fixtures that must all be contained.
