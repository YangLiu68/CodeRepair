import signal

import pytest


def _expired(signum, frame):
    raise TimeoutError("test exceeded its 2 second time limit")


@pytest.hookimpl(hookwrapper=True)
def pytest_pyfunc_call(pyfuncitem):
    """Fail (instead of hang) when a test function does not return within 2 seconds.

    The timer covers only the test function itself: it is disarmed before pytest's
    own teardown and reporting, so a long traceback is never interrupted mid-report.
    """
    previous = signal.signal(signal.SIGALRM, _expired)
    signal.setitimer(signal.ITIMER_REAL, 2.0)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
