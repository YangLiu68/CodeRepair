Backend `ollama` / model `qwen2.5-coder:3b`, budget {'max_calls': 3, 'max_tokens': 60000, 'max_wall_s': 900.0}, 2026-10-16T03:00:26+00:00, Darwin arm64 / Python 3.12.10, sandbox `seatbelt`.

| Agent | Resolved | 95% CI | pass@1 | Valid patch | Regressions | Mean calls | Mean tokens | Median LLM s | Median wall s |
|---|---|---|---|---|---|---|---|---|---|
| direct | 3/35 | 3–22% | 2/35 | 32/35 | 8 | 1.43 | 1899 | 13.0 | 14.5 |
| retrieval | 7/35 | 10–36% | 5/35 | 33/35 | 9 | 1.37 | 1932 | 11.9 | 13.3 |
| feedback | 5/35 | 6–29% | 5/35 | 33/35 | 8 | 2.43 | 4248 | 25.0 | 31.4 |
| feedback-sampled | 5/35 | 6–29% | 5/35 | 29/35 | 7 | 2.49 | 4319 | 27.3 | 32.3 |

Paired comparison on the same tasks (`Only A` / `Only B`: tasks exactly one of the two agents resolved):

| A vs B | Tasks | Only A | Only B | p (exact McNemar) |
|---|---|---|---|---|
| direct vs retrieval | 35 | 1 | 5 | 0.219 |
| direct vs feedback | 35 | 1 | 3 | 0.625 |
| direct vs feedback-sampled | 35 | 1 | 3 | 0.625 |
| retrieval vs feedback | 35 | 2 | 0 | 0.500 |
| retrieval vs feedback-sampled | 35 | 2 | 0 | 0.500 |
| feedback vs feedback-sampled | 35 | 0 | 0 | 1.000 |

| Task | direct | retrieval | feedback | feedback-sampled |
|---|---|---|---|---|
| q01_bitcount | resolved | resolved | resolved | resolved |
| q02_bucketsort | wrong-fix | resolved | resolved | resolved |
| q03_find_first_in_sorted | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q04_find_in_sorted | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q05_flatten | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q06_gcd | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q07_get_factors | syntax-error | wrong-fix | wrong-fix | wrong-fix |
| q08_hanoi | wrong-fix | wrong-fix | wrong-fix | anchor-mismatch |
| q09_kheapsort | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q10_kth | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q11_lcs_length | wrong-fix | syntax-error | wrong-fix | syntax-error |
| q12_lis | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q13_max_sublist_sum | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q14_mergesort | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q15_next_permutation | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q16_pascal | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q17_possible_change | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q18_powerset | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q19_rpn_eval | anchor-mismatch | anchor-mismatch | anchor-mismatch | anchor-mismatch |
| q20_shunting_yard | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q21_sieve | wrong-fix | resolved | resolved | resolved |
| q22_sqrt | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q23_subsequences | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| q24_to_base | wrong-fix | resolved | resolved | resolved |
| q25_wrap | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| t01_paginate_off_by_one | anchor-mismatch | resolved | anchor-mismatch | anchor-mismatch |
| t02_mutable_default_tags | regression | regression | regression | regression |
| t03_interval_merge_unsorted | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| t04_duration_whitespace | resolved | wrong-fix | wrong-fix | anchor-mismatch |
| t05_lru_recency | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
| t06_coupon_threshold_multifile | wrong-fix | resolved | wrong-fix | anchor-mismatch |
| t07_safe_join_prefix_escape | regression | regression | regression | regression |
| t08_money_half_up | regression | wrong-fix | wrong-fix | wrong-fix |
| t09_slugify_accents | resolved | resolved | resolved | resolved |
| t10_deep_merge_injection | wrong-fix | wrong-fix | wrong-fix | wrong-fix |
