"""Process-wide cap so jobs cannot stampede the Anthropic API."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from app.config import get_settings

_sonnet: threading.Semaphore | None = None
_lock = threading.Lock()


def _sem() -> threading.Semaphore:
    global _sonnet
    with _lock:
        if _sonnet is None:
            _sonnet = threading.Semaphore(max(1, get_settings().sonnet_max_concurrent))
        return _sonnet


@contextmanager
def sonnet_slot() -> Iterator[None]:
    sem = _sem()
    sem.acquire()
    try:
        yield
    finally:
        sem.release()
