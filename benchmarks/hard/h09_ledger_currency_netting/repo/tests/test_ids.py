from datetime import datetime, timedelta, timezone

import pytest

from billing.ids import InvoiceNumberer


def test_numbers_restart_every_year():
    numberer = InvoiceNumberer()
    assert numberer.next_number(datetime(2027, 12, 30, tzinfo=timezone.utc)) == "INV-2027-00001"
    assert numberer.next_number(datetime(2027, 12, 31, tzinfo=timezone.utc)) == "INV-2027-00002"
    assert numberer.next_number(datetime(2028, 1, 1, tzinfo=timezone.utc)) == "INV-2028-00001"


def test_the_year_is_the_issuers_local_year():
    numberer = InvoiceNumberer("LA", utc_offset_hours=-8)
    new_years_eve = datetime(2028, 1, 1, 5, 0, tzinfo=timezone.utc)  # 21:00 on Dec 31 in LA
    assert numberer.peek(new_years_eve) == "LA-2027-00001"
    tokyo = datetime(2027, 12, 31, 20, 0, tzinfo=timezone(timedelta(hours=9)))
    assert InvoiceNumberer().next_number(tokyo) == "INV-2027-00001"


def test_naive_times_are_refused():
    with pytest.raises(ValueError):
        InvoiceNumberer().next_number(datetime(2027, 1, 1))
