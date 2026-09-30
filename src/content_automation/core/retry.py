"""Timeout and retry helpers for provider calls.

Only errors that carry ``retryable = True`` are retried. Timeouts are not retried,
because a timed-out request may still be processed and billed by the provider.
"""

import threading
import time
from collections.abc import Callable


class OperationTimeoutError(TimeoutError):
    """The call did not finish within its time budget."""

    retryable = False


def is_retryable(error: BaseException) -> bool:
    return getattr(error, "retryable", False) is True


def run_with_timeout[T](fn: Callable[[], T], timeout_s: float) -> T:
    """Run fn in a daemon thread and stop waiting after timeout_s seconds.

    Python cannot kill the thread, so adapters should also pass their own
    request timeout to the provider client.
    """
    outcome: dict[str, object] = {}

    def target() -> None:
        try:
            outcome["value"] = fn()
        except BaseException as error:  # handed back to the calling thread
            outcome["error"] = error

    worker = threading.Thread(target=target, name="provider-call", daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        raise OperationTimeoutError(f"The provider did not respond within {timeout_s:g} seconds.")
    if "error" in outcome:
        raise outcome["error"]  # type: ignore[misc]
    return outcome["value"]  # type: ignore[return-value]


def call_with_retry[T](
    fn: Callable[[], T],
    *,
    timeout_s: float,
    max_retries: int,
    base_delay_s: float = 2.0,
    max_delay_s: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> T:
    """Call fn with a timeout; retry retryable errors up to max_retries times."""
    attempt = 0
    while True:
        try:
            return run_with_timeout(fn, timeout_s)
        except Exception as error:
            if attempt >= max_retries or not is_retryable(error):
                raise
            delay = min(base_delay_s * (2**attempt), max_delay_s)
            attempt += 1
            if on_retry is not None:
                on_retry(attempt, error, delay)
            sleep(delay)
