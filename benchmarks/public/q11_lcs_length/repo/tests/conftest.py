import signal

import pytest


@pytest.fixture(autouse=True)
def _time_limit():
    """Fail (instead of hang) when a call does not return within 2 seconds."""

    def _expired(signum, frame):
        raise TimeoutError("test exceeded its 2 second time limit")

    previous = signal.signal(signal.SIGALRM, _expired)
    signal.setitimer(signal.ITIMER_REAL, 2.0)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
