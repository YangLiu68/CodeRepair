# Benchmark

## Status

Milestone 1 builds the benchmark fixtures and measures retrieval only. **No repair rate is
reported yet**, because proposed patches are not executed until the Milestone 2 sandbox exists.
The comparative benchmark (direct-patch vs retrieval-assisted vs test-feedback agents under equal
budgets) is Milestone 5.

## Fixture tasks

Ten tiny first-party Python repositories, each with one seeded bug. All are original work written
for this project on 2026-10-14 (see LICENSE_NOTES.md); none are derived from public bug datasets.

| Task | Category | Difficulty | Issue style | Visible tests | Hidden tests | Fail-to-pass |
|---|---|---|---|---|---|---|
| `t01_paginate_off_by_one` | off-by-one | easy | behaviour description; names the public function | 5 | 2 | 3 (1 visible) |
| `t02_mutable_default_tags` | mutable-default-argument | easy | user report with repro steps; no code identifiers | 6 | 2 | 2 (0 visible) |
| `t03_interval_merge_unsorted` | algorithm-precondition | easy | failing test output; symptom in a caller of the buggy function | 5 | 2 | 3 (1 visible) |
| `t04_duration_whitespace` | input-parsing | easy | traceback with an absolute path from the reporter's machine | 9 | 3 | 2 (0 visible) |
| `t05_lru_recency` | state-management | easy | code repro plus failing test id | 6 | 2 | 3 (1 visible) |
| `t06_coupon_threshold_multifile` | boundary-condition | medium | symptom reported in cart total; root cause in a different module | 9 | 2 | 3 (1 visible) |
| `t07_safe_join_prefix_escape` | security-path-traversal | medium | security report (CWE-22) with a concrete exploit input | 6 | 3 | 2 (0 visible) |
| `t08_money_half_up` | numeric-precision | medium | short report with failing test id | 6 | 4 | 4 (1 visible) |
| `t09_slugify_accents` | unicode-handling | easy | user-visible symptom only; no identifiers or file names | 7 | 3 | 2 (0 visible) |
| `t10_deep_merge_injection` | recursion | medium | config example plus failing test id; repo contains prompt-injection payloads | 6 | 3 | 4 (1 visible) |

Six tasks ship a visible failing test (as if the reporter contributed one); four are issue-only, so
the bug is detectable only by hidden tests. That mix is deliberate: it lets M5 separate "made the
visible test pass" from "resolved the issue".

### Layout and leakage controls

```
benchmarks/tasks/<id>/
  issue.md        agent-visible
  repo/           agent-visible (the only directory the agent can read)
  task.toml       harness-only: category, fail_to_pass ids, provenance, revisions
  solution.json   harness-only: gold edits (same schema as an agent proposal)
  solution.patch  harness-only: gold diff, generated from solution.json
  hidden_tests/   harness-only: copied into repo/tests/ at evaluation time
benchmarks/manifest.json   SHA-256 of every task component
```

- The agent's ingestion root is `repo/`; the path policy rejects everything outside it.
- `test_agent.py` checks, for every task, that no gold-added line and no hidden-test line (that is
  not already visible) appears in the prompt. 9/10 tasks have gold lines to check; in t05 every
  gold line already occurs in the visible repo, so there is nothing secret to leak.
- The `oracle` backend replays `solution.json` to test the pipeline. Its output is labelled in the
  CLI, API, traces and summaries, and it is excluded from every metric.

### Validity criteria (checked by `coderepair validate-fixtures`)

For each task, on throwaway copies:

1. Buggy repo, visible tests: the visible fail-to-pass tests fail and all others pass.
2. Buggy repo + hidden tests: exactly the fail-to-pass tests fail.
3. Gold repo + hidden tests: every test passes.
4. At least one hidden test detects the bug.
5. The gold edits satisfy the same patch policy as agent edits (no test edits, exact anchors, valid syntax).
6. `solution.patch` and the manifest are current.

Current result: **10/10 valid**, manifest up to date.

### Provenance and revisions

- Created 2026-10-14 by the project author. Each `task.toml` records the seeded bug.
- **t08 revision (2026-10-14):** the local smoke run below produced `round(float(amount) * 100 + 0.5)`.
  That patch is wrong (for example `"0.01"` → 2 cents) but would have passed every visible and hidden
  test. I added the pass-to-pass hidden test `test_hidden_exact_cent_values_are_unchanged`. Hidden tests
  are not visible to the agent, so prompts are unchanged by this revision.

## Retrieval (measured)

`uv run coderepair eval-retrieval`, 10 tasks, ranking only non-test files:

| Metric | CodeRepair retrieval | Random ordering (expected) |
|---|---|---|
| recall@1 | **0.90** | 0.26 |
| recall@3 | **1.00** | 0.77 |
| recall@5 | 1.00 | 1.00 |
| MRR | 0.95 | — |

The only miss at rank 1 is t06, where the issue describes the cart total and the bug is in
`shop/coupons.py` (ranked 2nd behind `shop/cart.py`).

**Interpretation:** each repo has only 3–5 non-test files, so recall@3 is close to trivial and
recall@1 is the meaningful number. The retrieval weights (`retrieval.py`) were fixed before the
first evaluation and not tuned per task. One general change was made after inspecting the first run:
test files that import the top-ranked source module are now always eligible as context, even with no
lexical overlap. This affects which *test* files are shown, not the source ranking above. The fixtures
and the retriever have the same author, which biases results upward. M6 public tasks are the real test.

## Smoke run with a local model (not a benchmark)

One proposal per task with `qwen2.5:7b` through Ollama 0.14.2 on an Apple M4 (16 GB), temperature 0,
JSON-schema-constrained output, single shot, no retries. Raw results:
`docs/results/m1_smoke_ollama_qwen2.5-7b.json`. Reproduce with
`uv run python scripts/smoke_run.py --backend ollama`.

**Patches were not executed** (M1 has no sandbox), so "proposed" means only that a patch passed static
validation. The verdicts below come from reading the diffs, not from running tests.

| Task | Status | Diff vs gold | Manual reading of the patch |
|---|---|---|---|
| t01 | rejected | — | `old` contained a literal `\n` instead of a newline (JSON escaping) |
| t02 | rejected | — | `old` truncated at an embedded quote (JSON escaping) |
| t03 | rejected | — | `old` paraphrased the code (a docstring line was dropped); also targeted the symptom, not `merge()` |
| t04 | rejected | — | edit produced invalid Python |
| t05 | proposed | different | wrong: changes `__contains__` (contradicts its docstring); existing tests would fail |
| t06 | proposed | **identical** | correct |
| t07 | proposed | different | no-op (`abspath` does not fix the prefix check); hidden tests would fail |
| t08 | proposed | different | wrong `+ 0.5` rounding; exposed the weak test oracle fixed above |
| t09 | proposed | different | wrong (`xmlcharrefreplace` produces `caf-233`); hidden tests would fail |
| t10 | proposed | different | equivalent to gold; ignored the injection payload in the same file |

Summary: 6/10 passed static validation, 4/10 were rejected (3 anchor-format errors, 1 syntax error),
1/10 identical to gold, and about 2/10 correct by inspection. LLM latency was 36–107 s per task
(median 62 s, including a cold model load on the first task), with 0.9–1.6 k input and 77–141 output
tokens. Three unrelated CPU-bound training jobs were running on the same machine at the time, so
these latencies are pessimistic and not representative.

### Failure categories seen so far

| Category | Count | Planned response |
|---|---|---|
| Anchor not copied verbatim (escaping, paraphrase) | 3 | M3 retry loop feeds the validation error back to the model |
| Invalid syntax after edit | 1 | M3 retry with the parser error |
| Plausible but wrong fix | 4 | M2 sandboxed tests, M4 candidate ranking and hidden-test evaluation |
| Weak test oracle in the benchmark | 1 | Fixed (t08); M4 adds regression-test generation |

## Reproducibility

- Fixtures are pinned by `benchmarks/manifest.json`; the CI and test suite fail on any drift.
- Every run writes its full prompt, raw response, parsed proposal, validation result and diff to
  `runs/<run_id>/`.
- Python dependencies are pinned in `uv.lock`. The smoke run records model, date and machine.

## Limitations

- Ten tiny, single-language, single-bug repositories by one author: useful for plumbing, security
  tests and failure analysis, not for claims about general repair ability.
- Retrieval metrics are near ceiling because candidate sets are small.
- Exact gold match is a poor correctness signal (t10 shows a correct non-identical patch). M2 replaces
  it with test execution.
- One sample per task, one local model; no variance estimates yet.
