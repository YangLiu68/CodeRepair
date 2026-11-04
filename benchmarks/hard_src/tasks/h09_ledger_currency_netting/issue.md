# Journal accepted an entry that moved USD into a EUR account

Our auditor found a manual entry, "move funds", that debits cash:EUR with 100.00 EUR and credits
cash:USD with 100.00 USD. The journal accepted it, and the EUR cash account no longer matches the
bank statement.

Entries have to balance per currency; conversions are booked through the fx-clearing account.

`tests/test_ledger.py::test_entry_must_balance_in_each_currency` reproduces it.
