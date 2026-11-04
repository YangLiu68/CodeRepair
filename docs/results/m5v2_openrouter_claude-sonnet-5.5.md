Backend `openrouter` / model `anthropic/claude-sonnet-5.5`, budget {'max_calls': 3, 'max_tokens': 60000, 'max_wall_s': 900.0}, 2026-11-04T01:50:35+00:00, Darwin arm64 / Python 3.12.10, sandbox `seatbelt`.

| Agent | Resolved | 95% CI | pass@1 | Valid patch | Regressions | Mean calls | Mean tokens | Median LLM s | Median wall s |
|---|---|---|---|---|---|---|---|---|---|
| direct | 35/35 | 90–100% | 35/35 | 35/35 | 0 | 1 | 2490 | 2.7 | 3.4 |
| retrieval | 35/35 | 90–100% | 35/35 | 35/35 | 0 | 1 | 2584 | 2.9 | 3.5 |
| feedback | 35/35 | 90–100% | 35/35 | 35/35 | 0 | 1 | 2589 | 2.6 | 5.9 |

Cost reported by the provider: direct $0.2457, retrieval $0.2583, feedback $0.2599; total $0.7639.

Paired comparison on the same tasks (`Only A` / `Only B`: tasks exactly one of the two agents resolved):

| A vs B | Tasks | Only A | Only B | p (exact McNemar) |
|---|---|---|---|---|
| direct vs retrieval | 35 | 0 | 0 | 1.000 |
| direct vs feedback | 35 | 0 | 0 | 1.000 |
| retrieval vs feedback | 35 | 0 | 0 | 1.000 |

| Task | direct | retrieval | feedback |
|---|---|---|---|
| q01_bitcount | resolved | resolved | resolved |
| q02_bucketsort | resolved | resolved | resolved |
| q03_find_first_in_sorted | resolved | resolved | resolved |
| q04_find_in_sorted | resolved | resolved | resolved |
| q05_flatten | resolved | resolved | resolved |
| q06_gcd | resolved | resolved | resolved |
| q07_get_factors | resolved | resolved | resolved |
| q08_hanoi | resolved | resolved | resolved |
| q09_kheapsort | resolved | resolved | resolved |
| q10_kth | resolved | resolved | resolved |
| q11_lcs_length | resolved | resolved | resolved |
| q12_lis | resolved | resolved | resolved |
| q13_max_sublist_sum | resolved | resolved | resolved |
| q14_mergesort | resolved | resolved | resolved |
| q15_next_permutation | resolved | resolved | resolved |
| q16_pascal | resolved | resolved | resolved |
| q17_possible_change | resolved | resolved | resolved |
| q18_powerset | resolved | resolved | resolved |
| q19_rpn_eval | resolved | resolved | resolved |
| q20_shunting_yard | resolved | resolved | resolved |
| q21_sieve | resolved | resolved | resolved |
| q22_sqrt | resolved | resolved | resolved |
| q23_subsequences | resolved | resolved | resolved |
| q24_to_base | resolved | resolved | resolved |
| q25_wrap | resolved | resolved | resolved |
| t01_paginate_off_by_one | resolved | resolved | resolved |
| t02_mutable_default_tags | resolved | resolved | resolved |
| t03_interval_merge_unsorted | resolved | resolved | resolved |
| t04_duration_whitespace | resolved | resolved | resolved |
| t05_lru_recency | resolved | resolved | resolved |
| t06_coupon_threshold_multifile | resolved | resolved | resolved |
| t07_safe_join_prefix_escape | resolved | resolved | resolved |
| t08_money_half_up | resolved | resolved | resolved |
| t09_slugify_accents | resolved | resolved | resolved |
| t10_deep_merge_injection | resolved | resolved | resolved |
