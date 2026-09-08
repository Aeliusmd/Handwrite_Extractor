"""Process-wide caps so multiple jobs cannot stampede Document AI / Gemini."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from app.config import get_settings

_docai: threading.Semaphore | None = None
_gemini: threading.Semaphore | None = None
_lock = threading.Lock()


def _docai_sem() -> threading.Semaphore:
    global _docai
    with _lock:
        if _docai is None:
            _docai = threading.Semaphore(max(1, get_settings().docai_max_concurrent))
        return _docai


def _gemini_sem() -> threading.Semaphore:
    global _gemini
    with _lock:
        if _gemini is None:
            _gemini = threading.Semaphore(max(1, get_settings().gemini_max_concurrent))
        return _gemini


@contextmanager
def docai_slot() -> Iterator[None]:
    sem = _docai_sem()
    sem.acquire()
    try:
        yield
    finally:
        sem.release()


@contextmanager
def gemini_slot() -> Iterator[None]:
    sem = _gemini_sem()
    sem.acquire()
    try:
        yield
    finally:
        sem.release()
