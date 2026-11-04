Backend `openrouter` / model `anthropic/claude-haiku-5.5`, budget {'max_calls': 3, 'max_tokens': 60000, 'max_wall_s': 900.0}, 2026-11-04T02:52:59+00:00, Darwin arm64 / Python 3.12.10, sandbox `seatbelt`.

| Agent | Resolved | 95% CI | pass@1 | Valid patch | Regressions | Mean calls | Mean tokens | Median LLM s | Median wall s |
|---|---|---|---|---|---|---|---|---|---|
| direct | 8/9 | 57–98% | 8/9 | 8/9 | 0 | 1.22 | 29116 | 4.4 | 5.3 |
| retrieval | 6/9 | 35–88% | 6/9 | 6/9 | 0 | 1.67 | 17421 | 6.4 | 7.3 |
| feedback | 6/9 | 35–88% | 6/9 | 6/9 | 0 | 1.67 | 17604 | 5.4 | 9.4 |

Cost reported by the provider: direct $0.0297, retrieval $0.0202, feedback $0.0208; total $0.0707.

Paired comparison on the same tasks (`Only A` / `Only B`: tasks exactly one of the two agents resolved):

| A vs B | Tasks | Only A | Only B | p (exact McNemar) |
|---|---|---|---|---|
| direct vs retrieval | 9 | 3 | 1 | 0.625 |
| direct vs feedback | 9 | 3 | 1 | 0.625 |
| retrieval vs feedback | 9 | 0 | 0 | 1.000 |

| Task | direct | retrieval | feedback |
|---|---|---|---|
| h01_cycle_anchor_drift | resolved | resolved | resolved |
| h02_credit_allocation_sign | resolved | resolved | resolved |
| h03_vat_inclusive_discount | resolved | no-edits | no-edits |
| h04_volume_tier_boundary | resolved | no-edits | no-edits |
| h05_fx_intermediate_rounding | resolved | no-edits | no-edits |
| h06_csv_formula_injection | resolved | resolved | resolved |
| h07_coupon_counts_invoices | resolved | resolved | resolved |
| h08_dunning_recovery_resets_cycle | no-edits | resolved | resolved |
| h09_ledger_currency_netting | resolved | resolved | resolved |
