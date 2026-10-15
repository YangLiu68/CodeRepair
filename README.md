# CodeRepair

A constrained coding agent for small Python repositories. It reads an authorized issue,
finds the relevant files, proposes a minimal patch, and hands a human a reviewable diff.
Later milestones add sandboxed test execution, an iterative repair loop, and a
comparative benchmark. It never merges or pushes.

**Focus:** verifiable, test-driven repair with strong isolation and transparent evaluation.

## Status

| Milestone | State |
|---|---|
| M1: fixtures, ingestion, issue parsing, read-only search, patch proposal, diff display | **done** (see [PROGRESS.md](PROGRESS.md)) |
| M2: disposable, network-less test sandbox | blocked: no container runtime installed on the dev machine |
| M3–M7: repair loop, ranking and approval gate, benchmark, public subset, dashboard | not started |

What M1 does **not** do yet: run tests on proposed patches, retry, or write anything back.
A "proposed" patch has passed static validation only.

## Quickstart

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-extras                      # install (locked)
uv run coderepair tasks                   # the 10 seeded-bug benchmark tasks
uv run coderepair show t06_coupon_threshold_multifile
uv run coderepair retrieve t06_coupon_threshold_multifile    # ranked files + reasons
uv run coderepair propose t10_deep_merge_injection           # default: oracle mock backend
uv run coderepair propose t10_deep_merge_injection \
    --backend scripted --script docs/demo/malicious_response.json   # rejected
uv run coderepair validate-fixtures       # runs the fixtures' own tests (first-party only)
uv run coderepair eval-retrieval          # recall@k against gold files
uv run coderepair serve                   # local API + diff viewer on http://127.0.0.1:8000
uv run pytest                             # 190+ tests
```

The full walkthrough is in [docs/DEMO.md](docs/DEMO.md).

## Backends

| Backend | What it is | Use |
|---|---|---|
| `oracle` | **Mock.** Replays the task's gold solution | Pipeline check without a key. Never a repair result |
| `scripted` | **Mock.** Replays canned responses from a JSON file | Tests and adversarial demos |
| `anthropic` | Claude via the official SDK (default `claude-opus-5-5`), structured JSON output, server-side refusal fallback on | Real runs. Needs `ANTHROPIC_API_KEY` or an `ant auth login` profile |
| `ollama` | Local model via Ollama (default `qwen2.5:7b`), JSON-schema output | Offline real runs; nothing leaves the machine |

Configuration is environment-only; see [.env.example](.env.example).

## Measured so far

- Fixture validation: 10/10 tasks valid (bug reproduces, gold patch fixes it, hidden tests catch it).
- Retrieval on the 10 tasks: recall@1 = 0.90, recall@3 = 1.00, MRR = 0.95 (random baseline recall@1 = 0.26).
  These repositories are tiny (3–5 non-test files), so this mainly shows the plumbing works.
- One local smoke run with `qwen2.5:7b`: 6/10 proposals passed static validation, 1/10 matched the gold diff.
  The patches were not executed, so this is not a repair rate. See [BENCHMARK.md](BENCHMARK.md).

## Security posture (M1)

- Repositories are read into an in-memory snapshot. Only allowed roots are accepted, `$HOME` and credential
  directories are denied, and symlinks, binaries, oversized and credential-like files are skipped.
- No repository code, `git` command or model output is ever executed by the agent pipeline.
- Model output is parsed as data: exact search/replace edits, validated against a path policy. Tests, CI,
  build files and sensitive files are protected. Every patch is all-or-nothing and syntax-checked.
- Prompts fence repository and issue text as untrusted, escape closing tags, redact likely secrets, and flag
  prompt-injection text.
- The local API binds to loopback, checks the `Host` header, sends a strict CSP and renders all text with
  `textContent`.

Details and residual risks: [ARCHITECTURE.md](ARCHITECTURE.md).

## Layout

```
src/coderepair/        library, CLI (cli.py) and API (api.py)
  repo.py              read-only ingestion          security.py   path policy, redaction, injection scan
  issue.py             issue parsing                search.py     grep, symbols, imports, BM25
  retrieval.py         ranking with reasons         prompting.py  untrusted-content prompt builder
  patch.py             edit validation and diffs    agent.py      M1 pipeline and run artifacts
  llm/                 backend interface, scripted mock, Anthropic, Ollama
  benchmark/           tasks, oracle, fixture validator, manifest, retrieval eval (harness side)
benchmarks/tasks/      10 seeded-bug tasks (repo/, issue.md, hidden_tests/, solution.json, ...)
tests/                 unit, security and acceptance tests
docs/                  demo walkthrough, demo inputs, recorded results
```

## Documentation

[PLAN.md](PLAN.md) · [PROGRESS.md](PROGRESS.md) · [ARCHITECTURE.md](ARCHITECTURE.md) ·
[TESTING.md](TESTING.md) · [BENCHMARK.md](BENCHMARK.md) · [LICENSE_NOTES.md](LICENSE_NOTES.md) ·
[docs/DEMO.md](docs/DEMO.md)
