from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def retry_call(
    fn: Callable[[], T],
    *,
    retries: int = 6,
    base_delay: float = 2.0,
) -> T:
    delay = base_delay
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            text = str(exc).lower()
            retryable = any(
                token in text
                for token in (
                    "429",
                    "resource exhausted",
                    "deadline exceeded",
                    "unavailable",
                    "503",
                    "504",
                    "internal",
                )
            )
            not_retryable = any(
                token in text
                for token in (
                    "unauthenticated",
                    "permission",
                    "403",
                    "401",
                    "404",
                    "api has not been used",
                    "not found",
                    "invalid argument",
                    "failed to parse",
                )
            )
            if attempt == retries - 1 or not retryable or not_retryable:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 32)
    raise last_error or RuntimeError("retry_call failed")
