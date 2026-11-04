from datetime import date

import pytest

from billing.errors import UnbalancedEntry
from billing.ledger import Journal, Posting
from billing.money import Money

DAY = date(2027, 5, 1)


def m(text, currency):
    return Money.of(text, currency)


def test_hidden_currencies_are_never_netted():
    journal = Journal()
    attempts = [
        [Posting("cash:USD", m("100", "USD")), Posting("cash:EUR", m("-92", "EUR")), Posting("x", m("-8", "GBP"))],
        [Posting("a", m("5", "EUR")), Posting("b", m("-3", "EUR")), Posting("c", m("-2", "USD"))],
        [Posting("a", m("1", "JPY")), Posting("b", m("-1", "KWD"))],
    ]
    for postings in attempts:
        with pytest.raises(UnbalancedEntry):
            journal.post(DAY, "bad", postings)


def test_hidden_rejected_entries_leave_no_trace():
    journal = Journal()
    with pytest.raises(UnbalancedEntry):
        journal.post(DAY, "move funds", [Posting("cash:EUR", m("100", "EUR")), Posting("cash:USD", m("-100", "USD"))])
    assert journal.entries == []
    assert journal.trial_balance() == {}


def test_hidden_entries_balanced_per_currency_are_accepted():
    journal = Journal()
    journal.post(
        DAY,
        "three-way conversion",
        [
            Posting("cash:USD", m("-100.00", "USD")),
            Posting("fx-clearing", m("100.00", "USD")),
            Posting("fx-clearing", m("-92.00", "EUR")),
            Posting("cash:EUR", m("92.00", "EUR")),
            Posting("fees", m("0.50", "GBP")),
            Posting("cash:GBP", m("-0.50", "GBP")),
        ],
    )
    assert journal.balance("cash:EUR", "EUR") == m("92.00", "EUR")
    assert len(journal.entries) == 1
