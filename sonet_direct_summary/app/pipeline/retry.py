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
                    "529",
                    "rate_limit",
                    "overloaded",
                    "timeout",
                    "temporar",
                    "unavailable",
                    "503",
                    "504",
                    "internal",
                    "connection",
                )
            )
            not_retryable = any(
                token in text
                for token in (
                    "unauthenticated",
                    "invalid_api_key",
                    "permission",
                    "403",
                    "401",
                    "404",
                    "invalid_request",
                    "credit",
                )
            )
            if attempt == retries - 1 or not retryable or not_retryable:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 32)
    raise last_error or RuntimeError("retry_call failed")
