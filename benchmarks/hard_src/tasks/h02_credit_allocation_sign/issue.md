# Downgrade credits don't add up to the unused amount

Finance flagged proration invoices for downgrades. Example: sub_4471 was on Business
(3 seats at $30.00, Priority support $25.00, Extra storage $9.99: $124.99 a month) and moved to
Team (3 seats at $12.00) on April 29, with 11 of the period's 30 days left.

The unused time is $124.99 × 11/30 = $45.83, and that is the credit we promised. The proration
invoice shows:

```
Unused time on Business: Seats            -32.99
Unused time on Business: Priority support  -9.16
Unused time on Business: Extra storage     -3.65
Remaining time on Team: Seats              13.20
Total                                     -32.60
```

The credits add up to -$45.80, three cents short, and the total should be -$32.63. Upgrades
(where the prorated charge is the larger side) have always added up. The ledger team says the
difference shows up in their reconciliation every month.
