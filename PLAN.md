# CodeRepair — Plan

CodeRepair is a constrained coding agent: it reads an authorized issue for a small
repository, finds the relevant files, proposes a minimal patch, verifies it with tests
in an isolated sandbox, and hands a human a reviewable diff. It never merges or pushes.

Differentiator: verifiable, test-driven repair with strong sandbox isolation and
transparent, reproducible agent evaluation.

## Environment inspected (2026-10-14)

| Item | Finding | Consequence |
|---|---|---|
| Hardware | Apple M4, 10 cores, 16 GB RAM, ~27 GB free disk | Fine for fixtures and a 7B local model; no GPU work planned |
| Python | 3.12.10 (miniforge), 3.13.1; `uv` 0.9.2 | Project targets Python ≥ 3.11, dev env on 3.12, CI on 3.11–3.13 |
| Container runtime | **None** (no docker/podman/colima) | M2 ships a Docker backend (verified by command-line tests here, run for real in CI) and a macOS Seatbelt backend as the clearly labelled local fallback. There is still no unsandboxed fallback |
| LLM credentials | No API keys in the environment | Tests/CI use deterministic mock backends; real backends are optional |
| Local LLM | Ollama with `qwen2.5:7b` and `qwen2.5:3b` | Offline real-model runs; the shared machine's resource manager asks for ≤3B models, so M5 uses `qwen2.5:3b` |
| Git | Parent directory (`$HOME`) is itself a git repo | CodeRepair has its own `git init`; the tool never runs git on untrusted repos in M1 |

## Global non-goals

- No auto-merge, no push, no writing to a source repo without explicit human approval.
- No execution of repository code on the host, ever (first-party fixtures are the one documented exception, see M1).
- No arbitrary shell commands derived from LLM output. LLM output is parsed as data (structured edits) only.
- No cloning or executing arbitrary remote repositories; local fixtures first.
- No access to SSH keys, cloud credentials, personal directories, or the host Docker socket.
- No model training.

## Milestones

### M1 — Fixtures, ingestion, issue parsing, read-only search, patch proposal, diff display  (done)

Scope
- 10 tiny first-party Python repos with one seeded bug each, visible tests, held-out hidden tests, gold edits.
- Repository ingestion into an immutable in-memory snapshot (allowed-roots policy, denylist, symlink/binary/size/sensitive-file exclusion, content hash).
- Issue parsing (title, code blocks, tracebacks, file/symbol/test mentions, prompt-injection flags).
- Read-only code search: grep, Python symbol index, BM25 ranking; retrieval with explainable reasons.
- Patch proposal through one backend interface: `oracle` and `scripted` mocks, optional `anthropic` and `ollama`.
- Patch validation (path confinement, protected files, exact-unique anchors, syntax check, size limits) and unified diff display (CLI, saved run artifacts, minimal FastAPI viewer).
- Per-run trace (`runs/<id>/trace.jsonl`) with prompt, raw response, validation, diff.

Acceptance criteria
1. `coderepair validate-fixtures` passes for 10/10 tasks: every fail-to-pass test fails on the buggy repo, every other visible/hidden test passes; all tests pass with the gold edits; hidden tests detect the bug; manifest hashes match.
2. Ingestion refuses paths outside allowed roots and inside denylisted locations (`~/.ssh`, `~/.aws`, …, `$HOME` itself); skips `.git`, symlinks, binaries, oversized and sensitive files.
3. Issue parser extracts title, tracebacks, file paths, identifiers, test ids, and flags injection phrases (unit-tested).
4. Retrieval recall@3 of gold files ≥ 0.8 across the 10 tasks, reported with the real measured numbers (`coderepair eval-retrieval`).
5. Validation rejects: path traversal/absolute paths, edits to tests/CI/build config, missing or ambiguous anchors, edits producing Python syntax errors, oversized patches.
6. Oracle backend end-to-end reproduces the gold diff for 10/10 tasks (a pipeline check, **not** a repair metric).
7. Leakage check: for every task, the prompt contains no gold-added line and no hidden-test content.
8. Generated diffs apply cleanly with `git apply --check` on a temp copy.
9. `uv run pytest` and `uv run ruff check` pass locally; the same checks are wired into GitHub Actions without secrets.

Non-goals for M1: running tests on proposed patches, retries/iteration, writing back to repos, comparative benchmarks, creating new files in patches, non-Python repos.

Fixture-execution exception (documented): `validate-fixtures` runs pytest on **first-party fixtures only** (resolved under `benchmarks/tasks/`), on a temp copy, with a scrubbed environment, `HOME` set to a temp dir, and a timeout. The agent pipeline itself executes nothing.

### M2 — Isolated test execution  (done)

Disposable container per run: `--network none`, non-root user, CPU/memory/pids/time limits, read-only root filesystem and repo mount, a writable tmpfs workspace, no host env/secrets, no Docker socket. Results parsed as untrusted with size limits and a nonce.
Acceptance: escape/abuse fixtures (network call, fork bomb, writing outside workspace, reading `$HOME`, infinite loop) are all contained and reported.

**Decision (2026-10-15):** this machine has no container runtime, so the brief's "realistic local fallback, clearly labelled" applies: a macOS Seatbelt backend (`sandbox-exec`, deny-by-default) with rlimits and a memory/disk watchdog, labelled as weaker than a container wherever results are shown. `auto` prefers Docker. The Docker backend is unit-tested at the command-line level and exercised for real by CI.

### M3 — Iterative repair loop  (done)

Inspect failure → minimal patch → targeted tests → inspect → retry; bounded steps/tokens/time; full traces; stop on success or budget exhaustion.

### M4 — Candidate ranking and approval gate  (done)

Multiple candidates, ranking, regression-test generation (model-written reproduction tests that must fail on the original code), patch validation, lint/typecheck deltas, security checks on diffs, explicit human approval before writing to a source repo.

**Change from the original plan:** write-back does not use git at all (not even a hardened wrapper). `apply` re-verifies the approved diff against the current files and writes them directly, so repository git configuration can never run code.

### M5 — Comparative benchmark  (done; see BENCHMARK.md)

Direct-patch LLM vs retrieval-assisted vs test-feedback agent under equal call/token/time budgets. Metrics: pass@1, issue resolution (hidden tests), regressions, cost, steps, latency, failure categories.

### M6 — Public subset  (done)

12 tasks derived from QuixBugs (MIT), with provenance, leakage checks and contamination caveats.

### M7 — Dashboard and hardening  (done)

Dashboard (tasks, runs with traces and candidates, approvals, benchmark results, sandbox self-test), CI with a real Docker sandbox job, architecture and threat model, documentation and demo.

## Progress

See [PROGRESS.md](PROGRESS.md).
