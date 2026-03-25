"""Shared retry utility for transient Azure API errors."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 2.0
_TRANSIENT_CODES = {429, 502, 503}


def with_retry[T](fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Call *fn* with linear backoff on transient HTTP errors (429, 502, 503).

    Retries up to 3 times with delays of 2s, 4s, 6s.
    Non-transient exceptions are raised immediately.
    """
    for attempt in range(_MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            is_transient = status in _TRANSIENT_CODES or (
                status is None and any(str(c) in str(exc) for c in _TRANSIENT_CODES)
            )
            if is_transient and attempt < _MAX_RETRIES - 1:
                wait = _BASE_DELAY * (attempt + 1)
                logger.warning("Transient error (%s), retrying in %.1fs", status, wait)
                time.sleep(wait)
                continue
            raise
    msg = "Retry loop exhausted without return or raise"
    raise RuntimeError(msg)
