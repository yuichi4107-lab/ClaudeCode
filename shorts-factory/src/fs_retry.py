"""Small retry helpers for transient filesystem errors.

Google Drive File Provider sometimes raises EDEADLK while a file is being
hydrated or synced. Retrying only those transient I/O failures keeps the
pipeline from dropping a scheduled slot without hiding real errors.
"""
from __future__ import annotations

import errno
import signal
import threading
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

TRANSIENT_ERRNOS = {
    getattr(errno, "EDEADLK", 11),
    getattr(errno, "EAGAIN", 35),
    getattr(errno, "EBUSY", 16),
    getattr(errno, "ETIMEDOUT", 60),
}


def is_transient_io_error(exc: BaseException) -> bool:
    if not isinstance(exc, OSError):
        return False
    if exc.errno in TRANSIENT_ERRNOS:
        return True
    text = str(exc).lower()
    return "resource deadlock avoided" in text or "operation timed out" in text


def retry_io(
    func: Callable[[], T],
    *,
    attempts: int = 5,
    delay_sec: float = 2.0,
    backoff: float = 1.6,
) -> T:
    """Retry a callable for transient filesystem errors only."""
    wait = delay_sec
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except OSError as exc:
            if not is_transient_io_error(exc) or attempt >= attempts:
                raise
            if wait > 0:
                time.sleep(wait)
            wait *= backoff
    raise RuntimeError("unreachable")


def run_with_timeout(
    func: Callable[[], T],
    *,
    timeout_sec: float,
    label: str = "operation",
) -> T:
    """Run a blocking local operation with a short SIGALRM timeout.

    Google Drive File Provider can occasionally block inside a file read rather
    than raising EDEADLK immediately. The approval daemon runs on the main
    thread, so a POSIX alarm lets us treat that stall as a transient timeout and
    keep scanning the rest of the queue.
    """
    if (
        timeout_sec <= 0
        or threading.current_thread() is not threading.main_thread()
        or not hasattr(signal, "setitimer")
    ):
        return func()

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def _raise_timeout(_signum, _frame) -> None:
        raise OSError(errno.ETIMEDOUT, f"{label} timed out after {timeout_sec:.1f}s")

    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_sec)
    try:
        return func()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])
