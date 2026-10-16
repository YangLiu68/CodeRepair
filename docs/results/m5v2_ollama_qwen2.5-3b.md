Backend `ollama` / model `qwen2.5:3b`, budget {'max_calls': 3, 'max_tokens': 60000, 'max_wall_s': 900.0}, 2026-10-16T03:20:05+00:00, Darwin arm64 / Python 3.12.10, sandbox `seatbelt`.

| Agent | Resolved | 95% CI | pass@1 | Valid patch | Regressions | Mean calls | Mean tokens | Median LLM s | Median wall s |
|---|---|---|---|---|---|---|---|---|---|
| direct | 4/35 | 5–26% | 0/35 | 22/35 | 6 | 2.4 | 3422 | 41.4 | 42.5 |
| retrieval | 4/35 | 5–26% | 2/35 | 25/35 | 7 | 2.11 | 3109 | 28.2 | 29.5 |
| feedback | 2/35 | 2–19% | 2/35 | 23/35 | 7 | 2.74 | 4645 | 36.1 | 41.6 |
| feedback-sampled | 5/35 | 6–29% | 2/35 | 20/35 | 5 | 2.71 | 4498 | 37.8 | 41.9 |

Paired comparison on the same tasks (`Only A` / `Only B`: tasks exactly one of the two agents resolved):

| A vs B | Tasks | Only A | Only B | p (exact McNemar) |
|---|---|---|---|---|
| direct vs retrieval | 35 | 2 | 2 | 1.000 |
| direct vs feedback | 35 | 3 | 1 | 0.625 |
| direct vs feedback-sampled | 35 | 2 | 3 | 1.000 |
| retrieval vs feedback | 35 | 2 | 0 | 0.500 |
| retrieval vs feedback-sampled | 35 | 2 | 3 | 1.000 |
| feedback vs feedback-sampled | 35 | 0 | 3 | 0.250 |

| Task | direct | retrieval | feedback | feedback-sampled |
|---|---|---|---|---|
| q01_bitcount | resolved | resolved | resolved | resolved |
| q02_bucketsort | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q03_find_first_in_sorted | anchor-mismatch | wrong-fix | wrong-fix | anchor-mismatch |
| q04_find_in_sorted | syntax-error | wrong-fix | wrong-fix | anchor-mismatch |
| q05_flatten | resolved | resolved | syntax-error | syntax-error |
| q06_gcd | resolved | anchor-mismatch | wrong-fix | resolved |
| q07_get_factors | anchor-mismatch | wrong-fix | wrong-fix | wrong-fix |
| q08_hanoi | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q09_kheapsort | resolved | wrong-fix | wrong-fix | anchor-mismatch |
| q10_kth | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q11_lcs_length | wrong-fix | anchor-mismatch | wrong-fix | invalid-patch |
| q12_lis | wrong-fix | wrong-fix | wrong-fix | anchor-mismatch |
| q13_max_sublist_sum | regression | wrong-fix | anchor-mismatch | wrong-fix |
| q14_mergesort | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q15_next_permutation | anchor-mismatch | wrong-fix | anchor-mismatch | wrong-fix |
| q16_pascal | wrong-fix | invalid-patch | wrong-fix | wrong-fix |
| q17_possible_change | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q18_powerset | wrong-fix | anchor-mismatch | invalid-patch | anchor-mismatch |
| q19_rpn_eval | anchor-mismatch | wrong-fix | anchor-mismatch | resolved |
| q20_shunting_yard | wrong-fix | wrong-fix | anchor-mismatch | wrong-fix |
| q21_sieve | wrong-fix | regression | wrong-fix | regression |
| q22_sqrt | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q23_subsequences | anchor-mismatch | wrong-fix | invalid-patch | invalid-patch |
| q24_to_base | wrong-fix | resolved | wrong-fix | wrong-fix |
| q25_wrap | anchor-mismatch | wrong-fix | wrong-fix | anchor-mismatch |
| t01_paginate_off_by_one | wrong-fix | resolved | resolved | resolved |
| t02_mutable_default_tags | anchor-mismatch | anchor-mismatch | invalid-patch | invalid-patch |
| t03_interval_merge_unsorted | anchor-mismatch | wrong-fix | anchor-mismatch | anchor-mismatch |
| t04_duration_whitespace | wrong-fix | syntax-error | wrong-fix | anchor-mismatch |
| t05_lru_recency | wrong-fix | anchor-mismatch | anchor-mismatch | anchor-mismatch |
| t06_coupon_threshold_multifile | anchor-mismatch | wrong-fix | wrong-fix | wrong-fix |
| t07_safe_join_prefix_escape | wrong-fix | wrong-fix | wrong-fix | anchor-mismatch |
| t08_money_half_up | anchor-mismatch | anchor-mismatch | no-edits | wrong-fix |
| t09_slugify_accents | anchor-mismatch | anchor-mismatch | wrong-fix | resolved |
| t10_deep_merge_injection | invalid-patch | anchor-mismatch | invalid-patch | invalid-patch |
