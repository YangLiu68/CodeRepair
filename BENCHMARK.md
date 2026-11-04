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

### Public subset (`benchmarks/public/`, 25 tasks, Milestone 6)

Derived from [QuixBugs](https://github.com/jkoppel/QuixBugs) (MIT, commit `4257f44`) by
`scripts/build_public_subset.py`. **Selection rule (it never looks at model results):** every
self-contained program (no graph/node helpers) whose upstream correction passes every JSON test case,
whose correction finishes every case in under 0.5 s (a 4× margin below the 2-second per-test limit),
whose bug fails at least two cases (one is quoted in the issue or given as the visible failing test,
the others stay hidden), and whose outcomes are identical in two runs. Skipped under this rule:
`is_valid_parenthesization`, `next_palindrome` and `quicksort` (the bug fails only one case),
`knapsack`, `levenshtein` and `longest_common_subsequence` (the correction is too slow on some
cases; timing depends on the machine, so the committed manifest, not a rebuild, is the reference).

For each program the builder runs every upstream test case in the sandbox against the buggy and the
corrected version, then splits the cases: one failing case is the *reported example* (quoted in the
issue, and on every second task also given as a visible failing test), up to two passing cases are
visible, and the rest are hidden. The issue states the reported input, the expected output and what
the buggy program actually did (a value, an exception type, or "does not return within 2 seconds");
a per-test 2-second time limit in a protected `conftest.py` turns infinite loops into failures.
Long observed outputs keep their first and last 150 characters and say that the middle is omitted.

Two included programs specify more than one correct output, so their tests check the specification
rather than the one output the upstream correction happens to produce: `powerset` (subsets in any
order, elements of a subset in any order) and `subsequences` (the ascending sequences in any order).
The builder has the same kind of check for `longest_common_subsequence` ("either is OK"), which is
currently excluded as too slow.

**Revisions.**

1. *Before any model run (2026-10-15):* the first build quoted up to two failing cases in each
   issue, and for two tasks those were also hidden fail-to-pass cases, so a hard-coded patch could
   have scored. Found by the second independent review; the builder now quotes only a case that is
   never hidden and `test_public.py` checks this for every task.
2. *After the first M5 run (2026-10-15), v2:* (a) the 2-second timer was a pytest fixture, so it
   stayed armed while pytest formatted a failure report; a long traceback (a `RecursionError` in the
   buggy `flatten`) could be interrupted, aborting the session with `INTERNALERROR` and partial
   results. Found while rebuilding: the builder silently produced a different `q05` under load. The
   timer now wraps only the test call, aborted sessions are never treated as complete
   (`test_public.py`, `test_sandbox.py`), and the builder requires two identical runs. (b) Object
   addresses in observed values are masked so issues are reproducible (`q05`). (c) The subset was
   extended from the first 12 eligible programs to **all** eligible programs (25), to give the
   benchmark more tasks. (d) A third independent review then found that three tasks graded one
   valid output among several (now specification checks, see above), that a shortened observed
   output in `wrap` looked like the bug, that the corrections were never timed, and that the timer
   was still armed during pytest's own teardown (it now wraps only the test function); all fixed
   before any model ran on v2. The aborted sessions had also silently dropped failing cases from
   `flatten` and `mergesort` in the earlier builds; the builder now refuses incomplete sessions.
   Tasks `q01`–`q12` keep their ids and cases; their protected `conftest.py` changed (and `q05`'s
   issue), so the first M5 run's public rows were not reused.

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
| `q13_max_sublist_sum` | issue-only | 3 (0) | 2 |
| `q14_mergesort` | failing test provided | 7 (1) | 1 |
| `q15_next_permutation` | failing test provided | 7 (1) | 0 |
| `q16_pascal` | failing test provided | 4 (1) | 1 |
| `q17_possible_change` | issue-only | 6 (0) | 1 |
| `q18_powerset` | failing test provided | 4 (1) | 1 |
| `q19_rpn_eval` | issue-only | 2 (0) | 3 |
| `q20_shunting_yard` | failing test provided | 4 (1) | 2 |
| `q21_sieve` | issue-only | 4 (0) | 1 |
| `q22_sqrt` | failing test provided | 6 (1) | 1 |
| `q23_subsequences` | issue-only | 6 (0) | 2 |
| `q24_to_base` | failing test provided | 7 (1) | 3 |
| `q25_wrap` | failing test provided | 5 (1) | 0 |

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
are current. Current result: **35/35 valid** with the Seatbelt sandbox and with the Docker sandbox
(under Colima), 2026-10-15.

**Fixture revision (2026-10-14):** the M1 smoke run produced `round(float(amount) * 100 + 0.5)` for
t08, which is wrong (`"0.01"` → 2 cents) but passed every test. The hidden pass-to-pass test
`test_hidden_exact_cent_values_are_unchanged` was added; `test_sandbox.py` now checks that this exact
patch is rejected.

## Milestone 5: comparative benchmark

### Method

The agents get the same issue, snapshot, patch policy and per-task budget (**at most 3 model
calls**, 60k tokens, 900 s):

| Agent | Context | Uses tests? | Submits |
|---|---|---|---|
| `direct` | issue + repository files in path order (no retrieval, no repository map) | no | first statically valid patch among up to 3 samples |
| `retrieval` | issue + ranked, explained context (M1 prompt) | no | first statically valid patch among up to 3 samples |
| `feedback` | retrieval context + M3 loop: sandboxed visible tests after each valid patch, failures fed back | visible tests only | top-ranked candidate (M4 scorecard) after up to 3 attempts |
| `feedback-sampled` (ablation, `--agents` only) | as `feedback`, but retries 2 and 3 sample like the sampling agents (temperature 0.7, seeds 1 and 2) | visible tests only | as `feedback` |

Sample 0 is deterministic (temperature 0); further samples use temperature 0.7 with seeds 1 and 2,
for backends whose model accepts these parameters (Claude models on OpenRouter accept neither, so
every call there samples at the provider's default; see the Claude results).
The `feedback` loop's retries stay at temperature 0 (the prompt changes, the sampling does not), so
`feedback` versus `retrieval` changes two things at once; `feedback-sampled` changes only one.
The submitted patch is scored with the hidden tests in the sandbox: **resolved** means every
fail-to-pass and every pass-to-pass test passes. **pass@1** asks whether the agent's first model
call alone would have resolved the task (for `retrieval` and `feedback` this is the same
deterministic call, a built-in consistency check). Failure categories: `anchor-mismatch`,
`syntax-error`, `invalid-output`, `no-edits`, `policy-violation` (no valid patch), `wrong-fix`
(fail-to-pass tests still fail), `regression` (pass-to-pass broken), `resource-limit`.

### Results (v2: 35 tasks, two local 3B models)

**Runs:** `qwen2.5:3b` and `qwen2.5-coder:3b` through Ollama 0.14.2 on an Apple M4 (16 GB, shared
with other jobs), Seatbelt sandbox, 35 tasks × 4 agents = 140 rows per model, 2026-10-15/16. The
shared machine's resource manager asks for models of 3B or less; both models are under the Qwen
Research License (checked with `ollama show --license`) and were only run locally. For `qwen2.5:3b`
the 30 fixture rows of the three original agents come from the first run (same configuration and
task hashes); its public rows were re-run on subset v2. `feedback-sampled` was added afterwards to
the same files. Raw rows, summaries and per-task tables:
`docs/results/m5v2_ollama_{qwen2.5-3b,qwen2.5-coder-3b}.{jsonl,summary.json,md}`. Reproduce with
`CODEREPAIR_OLLAMA_MODEL=<model> uv run coderepair bench --suite all --backend ollama
--agents direct,retrieval,feedback,feedback-sampled --out <file>.jsonl`, then
`uv run coderepair bench-report <files>`.

| `qwen2.5:3b` | Resolved | 95% CI | pass@1 | Valid patch | Rows with a broken pass-to-pass test | Tokens (35 tasks) |
|---|---|---|---|---|---|---|
| direct | **4/35** | 5–26% | 0/35 | 22/35 | 6 | 120k |
| retrieval | **4/35** | 5–26% | 2/35 | 25/35 | 7 | 109k |
| feedback | **2/35** | 2–19% | 2/35 | 23/35 | 7 | 163k |
| feedback-sampled | **5/35** | 6–29% | 2/35 | 20/35 | 5 | 157k |

| `qwen2.5-coder:3b` | Resolved | 95% CI | pass@1 | Valid patch | Rows with a broken pass-to-pass test | Tokens (35 tasks) |
|---|---|---|---|---|---|---|
| direct | **3/35** | 3–22% | 2/35 | 32/35 | 8 | 66k |
| retrieval | **7/35** | 10–36% | 5/35 | 33/35 | 9 | 68k |
| feedback | **5/35** | 6–29% | 5/35 | 33/35 | 8 | 149k |
| feedback-sampled | **5/35** | 6–29% | 5/35 | 29/35 | 7 | 151k |

Paired over both models, one unit per task (exact sign-flip test on the per-task difference in
resolved runs, so the two models' runs of a task are not counted as independent evidence):

| A vs B | A − B (resolved runs, of 70) | p |
|---|---|---|
| direct vs retrieval | −4 | 0.438 |
| direct vs feedback | 0 | 1.000 |
| direct vs feedback-sampled | −3 | 0.508 |
| retrieval vs feedback | +4 | 0.125 |
| retrieval vs feedback-sampled | +1 | 1.000 |
| feedback vs feedback-sampled | −3 | 0.250 |

Where the resolutions came from. The first call is the same deterministic request for `retrieval`,
`feedback` and `feedback-sampled`, and their `pass@1` agrees in both runs (2 and 5), as it must:

| Source | `qwen2.5:3b` | `qwen2.5-coder:3b` |
|---|---|---|
| first call | 2 (`q01`, `t01`) | 5 (`q01`, `q02`, `q21`, `q24`, `t09`) |
| `retrieval`: a temperature-0.7 sample after an invalid first patch | +2 (`q05`, `q24`) | +2 (`t01`, `t06`) |
| `feedback`: retries with test feedback, temperature 0 | +0 of 33 | +0 of 30 |
| `feedback-sampled`: retries with test feedback, sampled | +3 (`q06`, `q19`, `t09`) | +0 of 30 |

**What this shows, and what it does not:**

- Neither model is strong enough to rank the agents. The best cell is 7/35 (95% CI 10–36%), and no
  pairwise difference is significant: the smallest p-value is 0.125 (retrieval vs feedback, pooled).
  **This benchmark does not show that test feedback resolves more issues**; with these models it
  does not.
- Test feedback at temperature 0 never turned a failed first attempt into a resolved task, for
  either model (0 of 63 chances). The fed-back failures changed the prompt but not the outcome: the
  retries mostly produced other wrong fixes.
- The gap between `retrieval` and `feedback` (+4 runs pooled) came entirely from sampling: every
  task `retrieval` resolved beyond its first call was a temperature-0.7 resample after an invalid
  patch. With sampled retries, the loop recovered 3 tasks for `qwen2.5:3b` and none for the coder
  model; `feedback-sampled` vs `retrieval` is +1 for retrieval (p = 1.0). So the first run's
  apparent "feedback is no better" mixes two effects, and neither is measurable at this model size.
- `qwen2.5-coder:3b` almost never fails on the edit format (valid patches 29–33/35 against 20–25/35
  for `qwen2.5:3b`), yet resolves only 3–7 tasks: once the format is right, the remaining failures
  are wrong fixes (22–26 rows per agent).
- The feedback agents cost 1.4–1.5× (`qwen2.5:3b`) and 2.2× (coder) the tokens of `retrieval`.
- No sign of a memorisation advantage on the public (QuixBugs) subset: 24/200 agent runs resolved
  on public tasks (12%) against 11/80 on the first-party fixtures (14%).
- Run-to-run variation is real. In the first run (below) `feedback` resolved `q03` after test
  feedback; in v2 it did not (its conftest changed with the subset, and temperature-0 Ollama calls
  are not guaranteed to repeat exactly).

### Results (v2: Claude Haiku 5.5 and Sonnet 5.5 through OpenRouter)

**Runs:** `anthropic/claude-haiku-5.5` and `anthropic/claude-sonnet-5.5` through the `openrouter`
backend, 2026-11-04, same 35 tasks, budget and Seatbelt sandbox as the 3B runs, provider-default
reasoning, `data_collection: deny`. Three agents (`feedback-sampled` would send the same requests as
`feedback`, because these models accept no `temperature`). Raw rows, summaries and per-task tables:
`docs/results/m5v2_openrouter_{claude-haiku-5.5,claude-sonnet-5.5}.{jsonl,summary.json,md}`.
Reproduce with `CODEREPAIR_OPENROUTER_MODEL=<model> uv run coderepair bench --suite all
--backend openrouter --sandbox seatbelt --max-cost-usd <cap> --out <file>.jsonl` (needs
`OPENROUTER_API_KEY`).

| Agent | Haiku 5.5 resolved | 95% CI | pass@1 | Sonnet 5.5 resolved | 95% CI | pass@1 |
|---|---|---|---|---|---|---|
| direct | **35/35** | 90–100% | 35/35 | **35/35** | 90–100% | 35/35 |
| retrieval | **34/35** | 85–99% | 33/35 | **35/35** | 90–100% | 35/35 |
| feedback | **35/35** | 90–100% | 35/35 | **35/35** | 90–100% | 35/35 |

| | Haiku 5.5 | Sonnet 5.5 |
|---|---|---|
| Cost (105 rows, provider-reported) | $0.054 | $0.764 |
| Most expensive row | $0.0023 | $0.0149 |
| Mean tokens per row (direct / retrieval / feedback) | 2792 / 3020 / 2830 | 2490 / 2584 / 2589 |
| Median wall time per row (direct / retrieval / feedback) | 3.8 / 3.9 / 6.3 s | 3.4 / 3.5 / 5.9 s |
| Rows that needed more than one call | 1 | 0 |

**What this shows:**

- **The benchmark saturates.** Sonnet resolved all 105 (task, agent) pairs with its first call;
  Haiku resolved 104. No paired difference exists to test (Haiku: retrieval lost `q03` once, p = 1.0).
  At this level the 35 tasks cannot rank the agents in either direction; ranking them needs harder
  tasks (larger repositories, misleading issues, bugs whose fix spans files), not more runs.
- It is not only memorisation of QuixBugs: the ten first-party fixtures, written for this project,
  saturate too (30/30 per model).
- Haiku's two imperfect rows were both `retrieval`: `q03` was a wrong fix on the only call, and `q12`
  needed a second sample after an invalid first patch. `feedback` sends the same first request and
  resolved both on the first call. Without temperature control the first call is a sample, so the
  `pass@1` agreement between `retrieval` and `feedback` that held at temperature 0 (3B runs) is not
  expected here, and one disagreement is noise, not a finding.
- With a model that gets it right the first time, the agents differ only in cost: tokens are
  within 10% of each other, and `feedback` adds about 2.5 s per row for its visible-test run.
- Accounting check: the key's usage rose by $0.8221 over the pilot, both runs and one probe call;
  the rows record $0.0544 + $0.7639, the pilot $0.0036 and the probe $0.0001.

**First run (2026-10-15, subset v1, 22 tasks, `qwen2.5:3b`, three agents):** direct 1/22,
retrieval 3/22, feedback 3/22; valid patches 11/14/17. Its public rows were measured on the v1
`conftest.py` with the timer bug (see Revisions) and are superseded by v2; the apparent rise in
valid patches from direct to feedback did not replicate in v2. Raw rows:
`docs/results/m5_ollama_qwen2.5-3b.{jsonl,summary.json,md}`.

**Next:** 3B models are too weak and current hosted models too strong for these 35 tasks. Ranking
the agents needs a harder task tier between the two (or a mid-size local model on this one); the
harness, the ablation, the statistics and the spend cap run unchanged on any new suite.

## Milestone 1 smoke run (historical, patches not executed)

One proposal per fixture with `qwen2.5:7b`, before the sandbox existed: 6/10 passed static
validation, 4/10 were rejected (3 anchor-format errors, 1 syntax error), 1/10 matched the gold diff
and about 2/10 looked correct on reading. Raw results: `docs/results/m1_smoke_ollama_qwen2.5-7b.json`.
These anchor errors motivated the loop's anchor hints.

## Reproducibility

- Tasks are pinned by manifests; CI and the test suite fail on any drift.
- `coderepair bench` appends one JSON row per (task, agent) to a JSONL file and resumes an
  interrupted run with the same configuration; `<name>.summary.json` and `<name>.md` are written
  next to it. The agent list is not part of the configuration, so adding an agent (as was done for
  `feedback-sampled`) runs only the new rows. `coderepair bench-report` recomputes intervals and
  paired tests from the JSONL files and ignores rows whose task content has since changed. Every row
  records backend, model, calls, tokens, latency, the failure category and, for hosted backends,
  the provider-reported cost (`cost_usd`, including billed calls that failed). `--max-cost-usd`
  starts no new row once a run's cost reaches the cap; re-running resumes. Backend settings that
  change answers (OpenRouter: reasoning effort, data-collection policy, max tokens) are part of the
  configuration fingerprint.
- Repair runs write prompts, responses, feedback, attempts, candidates and traces to `runs/<id>/`.

## Limitations

- Small: 35 tasks, single-file or few-file Python repositories, one bug each. Useful for comparing
  agent designs and failure modes, not for claims about general repair ability.
- One run per configuration. With the two local 3B models the 95% intervals are 20–30 percentage
  points wide and no agent difference is significant; temperature-0 calls are not guaranteed to
  repeat exactly. With the two Claude models every agent is at or near 35/35, so there is nothing
  to compare.
- The hosted runs depend on OpenRouter's routing: a call may be served by different providers of
  the same model (each response names its provider, but benchmark rows do not keep it).
- The public subset is likely memorised by large models (see Contamination).
- Retrieval metrics are near ceiling on the fixtures because candidate sets are small.
