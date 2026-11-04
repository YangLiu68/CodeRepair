from datetime import date, datetime, timedelta, timezone

import pytest

from billing.dates import Period
from billing.usage import UsageEvent, UsageLog

MARCH = Period(date(2027, 3, 1), date(2027, 4, 1))
APRIL = Period(date(2027, 4, 1), date(2027, 5, 1))


def at(*args, tz=timezone.utc):
    return datetime(*args, tzinfo=tz)


def event(quantity, when, key=None, component="api_calls"):
    return UsageEvent("sub_1", component, quantity, when, key)


def test_sum_max_and_last():
    log = UsageLog(
        [event(5, at(2027, 3, 2)), event(9, at(2027, 3, 20)), event(3, at(2027, 3, 31, 23))]
    )
    assert log.total("sub_1", "api_calls", MARCH) == 17
    assert log.total("sub_1", "api_calls", MARCH, "max") == 9
    assert log.total("sub_1", "api_calls", MARCH, "last") == 3
    assert log.total("sub_1", "storage_gb", MARCH) == 0


def test_an_event_on_the_period_end_belongs_to_the_next_period():
    log = UsageLog([event(40, at(2027, 3, 31, 12)), event(7, at(2027, 4, 1, 0, 0))])
    assert log.total("sub_1", "api_calls", MARCH) == 40
    assert log.total("sub_1", "api_calls", APRIL) == 7


def test_periods_use_the_utc_date():
    eastern = timezone(timedelta(hours=-5))
    log = UsageLog([event(2, at(2027, 3, 31, 21, 30, tz=eastern))])  # 02:30 UTC on April 1
    assert log.total("sub_1", "api_calls", MARCH) == 0
    assert log.total("sub_1", "api_calls", APRIL) == 2


def test_idempotency_keys_drop_retries():
    log = UsageLog()
    assert log.record(event(10, at(2027, 3, 5), key="req-1"))
    assert not log.record(event(10, at(2027, 3, 5, 0, 1), key="req-1"))
    assert log.record(event(10, at(2027, 3, 5, 0, 2)))
    assert log.total("sub_1", "api_calls", MARCH) == 20


def test_events_must_be_timezone_aware_and_non_negative():
    with pytest.raises(ValueError):
        event(1, datetime(2027, 3, 1))
    with pytest.raises(ValueError):
        event(-1, at(2027, 3, 1))
