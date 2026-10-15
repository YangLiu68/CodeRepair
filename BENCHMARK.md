# Benchmark

Two task suites, hidden-test scoring in the sandbox, and a comparative benchmark of three repair
agents under equal budgets (Milestone 5). Every number below was produced by a command in this
repository; the raw rows are in `docs/results/`.

## Task suites

### First-party fixtures (`benchmarks/tasks/`, 10 tasks)

Ten tiny Python repositories, each with one seeded bug, written for this project on 2026-10-14
(see LICENSE_NOTES.md); none are derived from public bug datasets.

| Task | Category | Difficulty | Issue style | Fail-to-pass (visible) | Pass-to-pass |
|---|---|---|---|---|---|
| `t01_paginate_off_by_one` | off-by-one | easy | behaviour description; names the public function | 3 (1) | 4 |
| `t02_mutable_default_tags` | mutable-default-argument | easy | user report with repro steps; no code identifiers | 2 (0) | 6 |
| `t03_interval_merge_unsorted` | algorithm-precondition | easy | failing test output; symptom in a caller | 3 (1) | 4 |
| `t04_duration_whitespace` | input-parsing | easy | traceback with an absolute path from the reporter's machine | 2 (0) | 10 |
| `t05_lru_recency` | state-management | easy | code repro plus failing test id | 3 (1) | 5 |
| `t06_coupon_threshold_multifile` | boundary-condition | medium | symptom in cart total; root cause in another module | 3 (1) | 8 |
| `t07_safe_join_prefix_escape` | security-path-traversal | medium | security report (CWE-22) with an exploit input | 2 (0) | 7 |
| `t08_money_half_up` | numeric-precision | medium | short report with failing test id | 4 (1) | 6 |
| `t09_slugify_accents` | unicode-handling | easy | user-visible symptom only | 2 (0) | 8 |
| `t10_deep_merge_injection` | recursion | medium | config example + failing test id; repo contains prompt-injection payloads | 4 (1) | 5 |

### Public subset (`benchmarks/public/`, 12 tasks, Milestone 6)

Derived from [QuixBugs](https://github.com/jkoppel/QuixBugs) (MIT, commit `4257f44`) by
`scripts/build_public_subset.py`. **Selection rule, fixed before any model was run on these tasks:**
the first 12 programs in alphabetical order that are self-contained (no graph/node helpers), whose
upstream correction passes every JSON test case, and whose bug fails at least two cases (one is
quoted in the issue or given as the visible failing test, the others stay hidden). Skipped under
this rule: `is_valid_parenthesization` (one failing case), `knapsack` (test session exceeded the
sandbox memory limit), `levenshtein` (the correction exceeds the 2-second per-test limit on one case).

**Revision (2026-10-15, before any model run on the subset):** the first build quoted up to two
failing cases in each issue, and for two tasks those were also hidden fail-to-pass cases, so a
hard-coded patch could have scored. Found by the second independent review; the builder now quotes
only a case that is never hidden, `test_public.py` checks this for every task, and the subset was
rebuilt: `is_valid_parenthesization` was replaced by `lis`, and the ids of the last four tasks
shifted.

For each program the builder runs every upstream test case in the sandbox against the buggy and the
corrected version, then splits the cases: one failing case is the *reported example* (quoted in the
issue, and on every second task also given as a visible failing test), up to two passing cases are
visible, and the rest are hidden. The issue states the reported input, the expected output and what
the buggy program actually did (a value, an exception type, or "does not return within 2 seconds");
a per-test 2-second time limit in a protected `conftest.py` turns infinite loops into failures.

| Task | Issue style | Fail-to-pass (visible) | Pass-to-pass |
|---|---|---|---|
| `q01_bitcount` | failing test provided | 7 (1) | 0 |
| `q02_bucketsort` | failing test provided | 6 (1) | 1 |
| `q03_find_first_in_sorted` | issue-only | 2 (0) | 4 |
| `q04_find_in_sorted` | failing test provided | 2 (1) | 5 |
| `q05_flatten` | issue-only | 5 (0) | 1 |
| `q06_gcd` | failing test provided | 5 (1) | 1 |
| `q07_get_factors` | issue-only | 6 (0) | 1 |
| `q08_hanoi` | failing test provided | 7 (1) | 1 |
| `q09_kheapsort` | issue-only | 2 (0) | 1 |
| `q10_kth` | failing test provided | 4 (1) | 3 |
| `q11_lcs_length` | issue-only | 6 (0) | 1 |
| `q12_lis` | failing test provided | 4 (1) | 6 |

### Layout and leakage controls (both suites)

```
<suite>/<id>/
  issue.md        agent-visible
  repo/           agent-visible (the only directory the agent can read)
  task.toml       harness-only: fail_to_pass, pass_to_pass, provenance, revisions
  solution.json   harness-only: gold edits (same schema as an agent proposal)
  solution.patch  harness-only: gold diff
  hidden_tests/   harness-only: added to repo/tests/ at scoring time
<suite>/manifest.json   SHA-256 of every task component
```

- The agent's ingestion root is `repo/`; nothing else is readable to it, and the sandbox cannot read
  the benchmark directories either (`host-files` probe).
- Tests check every prompt, for every task in both suites, for gold-added lines and hidden-test
  lines (`test_agent.py`, `test_public.py`). The repair loop only ever runs visible tests.
- Public tasks contain no QuixBugs name, upstream harness or corrected code in `repo/` or the issue.
- **Contamination:** QuixBugs has been public since 2017 and is very likely in the training data of
  current models. Results on the public subset can reflect memorisation, which is why both suites are
  reported separately and why the first-party fixtures exist.
- The `oracle` backend replays gold solutions to test the pipeline; it is labelled everywhere and
  excluded from every result table.

### Validity checks (`coderepair validate-fixtures --suite all`)

For each task, on throwaway copies (public tasks always in the sandbox): visible fail-to-pass tests
fail on the buggy repo and all others pass; with hidden tests exactly the fail-to-pass tests fail and
exactly the pass-to-pass tests pass; with the gold edits every test passes; at least one hidden test
detects the bug; the gold edits satisfy the agent's patch policy; `solution.patch` and the manifest
are current. Current result: **22/22 valid**.

**Fixture revision (2026-10-14):** the M1 smoke run produced `round(float(amount) * 100 + 0.5)` for
t08, which is wrong (`"0.01"` → 2 cents) but passed every test. The hidden pass-to-pass test
`test_hidden_exact_cent_values_are_unchanged` was added; `test_sandbox.py` now checks that this exact
patch is rejected.

## Milestone 5: comparative benchmark

### Method

Three agents get the same issue, snapshot, patch policy and per-task budget (**at most 3 model
calls**, 60k tokens, 900 s):

| Agent | Context | Uses tests? | Submits |
|---|---|---|---|
| `direct` | issue + repository files in path order (no retrieval, no repository map) | no | first statically valid patch among up to 3 samples |
| `retrieval` | issue + ranked, explained context (M1 prompt) | no | first statically valid patch among up to 3 samples |
| `feedback` | retrieval context + M3 loop: sandboxed visible tests after each valid patch, failures fed back | visible tests only | top-ranked candidate (M4 scorecard) after up to 3 attempts |

Sample 0 is deterministic (temperature 0); further samples use temperature 0.7 with seeds 1 and 2.
The submitted patch is scored with the hidden tests in the sandbox: **resolved** means every
fail-to-pass and every pass-to-pass test passes. **pass@1** asks whether the agent's first model
call alone would have resolved the task (for `retrieval` and `feedback` this is the same
deterministic call, a built-in consistency check). Failure categories: `anchor-mismatch`,
`syntax-error`, `invalid-output`, `no-edits`, `policy-violation` (no valid patch), `wrong-fix`
(fail-to-pass tests still fail), `regression` (pass-to-pass broken), `resource-limit`.

### Results

M5_RESULTS_PLACEHOLDER

## Milestone 1 smoke run (historical, patches not executed)

One proposal per fixture with `qwen2.5:7b`, before the sandbox existed: 6/10 passed static
validation, 4/10 were rejected (3 anchor-format errors, 1 syntax error), 1/10 matched the gold diff
and about 2/10 looked correct on reading. Raw results: `docs/results/m1_smoke_ollama_qwen2.5-7b.json`.
These anchor errors motivated the loop's anchor hints.

## Reproducibility

- Tasks are pinned by manifests; CI and the test suite fail on any drift.
- `coderepair bench` appends one JSON row per (task, agent) to a JSONL file and resumes an
  interrupted run with the same configuration; `<name>.summary.json` and `<name>.md` are written
  next to it. Every row records backend, model, calls, tokens, latency and the failure category.
- Repair runs write prompts, responses, feedback, attempts, candidates and traces to `runs/<id>/`.

## Limitations

- Small: 22 tasks, single-file or few-file Python repositories, one bug each. Useful for comparing
  agent designs and failure modes, not for claims about general repair ability.
- One local 3B model, one sample per configuration, no confidence intervals. Differences of one or
  two tasks are within noise.
- The public subset is likely memorised by large models (see Contamination).
- Retrieval metrics are near ceiling on the fixtures because candidate sets are small.
