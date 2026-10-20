"""Builds in a small pool that overlap only their provider HTTP calls (2026-10-21).

Every task holds one shared lock while it runs, so registry writes, authorizations, cost
tracking, idempotency keys and files stay one at a time exactly as in a sequential build; the
lock is released only inside `released()`, around an OpenRouter image or text-check request.
A Higgsfield job never releases it (Codex runs one plugin job at a time). One worker, or one
task, runs everything in order on the calling thread.
"""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

_LOCK = threading.Lock()
_STATE = threading.local()


@contextmanager
def released() -> Iterator[None]:
    """Let the other tasks run while this one waits for a provider (no-op outside a pool)."""
    if not getattr(_STATE, "held", False):
        yield
        return
    _STATE.held = False
    _LOCK.release()
    try:
        yield
    finally:
        _LOCK.acquire()
        _STATE.held = True


def run_all[T](tasks: list[Callable[[], T]], workers: int) -> list[T | BaseException]:
    """Each task's result or its exception, in the order given."""
    if workers <= 1 or len(tasks) <= 1:
        found: list[T | BaseException] = []
        for task in tasks:
            try:
                found.append(task())
            except Exception as error:  # reported per task, like the pool
                found.append(error)
        return found

    def locked(task: Callable[[], T]) -> T:
        with _LOCK:
            _STATE.held = True
            try:
                return task()
            finally:
                _STATE.held = False

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(contextvars.copy_context().run, locked, task) for task in tasks]
        results: list[T | BaseException] = []
        for future in futures:
            failure = future.exception()
            results.append(failure if failure is not None else future.result())
        return results


__all__ = ["released", "run_all"]
