Backend `ollama` / model `qwen2.5:3b`, budget {'max_calls': 3, 'max_tokens': 60000, 'max_wall_s': 900.0}, 2026-10-15T13:43:04+00:00, Darwin arm64 / Python 3.12.10, sandbox `seatbelt`.

| Agent | Resolved | pass@1 | Valid patch | Regressions | Mean calls | Mean tokens | Median LLM s | Median wall s |
|---|---|---|---|---|---|---|---|---|
| direct | 1/22 | 0/22 | 11/22 | 4 | 2.36 | 3280 | 30.0 | 30.0 |
| retrieval | 3/22 | 2/22 | 14/22 | 5 | 2.23 | 3272 | 30.2 | 30.6 |
| feedback | 3/22 | 2/22 | 17/22 | 7 | 2.59 | 4470 | 30.6 | 32.5 |

| Task | direct | retrieval | feedback |
|---|---|---|---|
| q01_bitcount | resolved | resolved | resolved |
| q02_bucketsort | wrong-fix | wrong-fix | wrong-fix |
| q03_find_first_in_sorted | anchor-mismatch | wrong-fix | resolved |
| q04_find_in_sorted | regression | anchor-mismatch | regression |
| q05_flatten | anchor-mismatch | wrong-fix | wrong-fix |
| q06_gcd | wrong-fix | resolved | wrong-fix |
| q07_get_factors | invalid-patch | wrong-fix | wrong-fix |
| q08_hanoi | wrong-fix | wrong-fix | wrong-fix |
| q09_kheapsort | wrong-fix | wrong-fix | wrong-fix |
| q10_kth | syntax-error | wrong-fix | wrong-fix |
| q11_lcs_length | anchor-mismatch | syntax-error | wrong-fix |
| q12_lis | wrong-fix | wrong-fix | wrong-fix |
| t01_paginate_off_by_one | wrong-fix | resolved | resolved |
| t02_mutable_default_tags | anchor-mismatch | anchor-mismatch | invalid-patch |
| t03_interval_merge_unsorted | anchor-mismatch | wrong-fix | anchor-mismatch |
| t04_duration_whitespace | wrong-fix | syntax-error | wrong-fix |
| t05_lru_recency | wrong-fix | anchor-mismatch | anchor-mismatch |
| t06_coupon_threshold_multifile | anchor-mismatch | wrong-fix | wrong-fix |
| t07_safe_join_prefix_escape | wrong-fix | wrong-fix | wrong-fix |
| t08_money_half_up | anchor-mismatch | anchor-mismatch | no-edits |
| t09_slugify_accents | anchor-mismatch | anchor-mismatch | wrong-fix |
| t10_deep_merge_injection | invalid-patch | anchor-mismatch | invalid-patch |
