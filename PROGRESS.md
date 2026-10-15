# Progress log

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
