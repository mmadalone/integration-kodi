"""
Artwork download retry schedule for the Kodi integration (fork patch 50).

Pure bookkeeping, no asyncio and no I/O: KodiDevice owns the single retry task
and asks this object how long to wait before the next attempt, or whether to
give up on the current URL.

:copyright: (c) 2026 by madalone.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import random
from enum import Enum
from typing import NamedTuple

# Delays before each retry after a transient failure (timeout, connection error, 5xx,
# empty body). The last value repeats for as long as the same artwork is wanted.
TRANSIENT_RETRY_DELAYS: tuple[float, ...] = (0.5, 1.5, 4.0, 8.0, 16.0, 32.0, 60.0)
# Kodi answered 4xx (404 missing image, 401 bad credentials). Two quick retries cover
# a texture cache that is still being filled, then the URL is given up.
NOT_FOUND_RETRY_DELAYS: tuple[float, ...] = (0.5, 1.5)
# Up to +20% so concurrent retries against one Kodi don't synchronise (as patch 37).
RETRY_JITTER = 0.2


class FetchOutcome(Enum):
    """Result class of one artwork download attempt."""

    OK = "ok"
    NOT_FOUND = "not_found"
    TRANSIENT = "transient"


class FetchResult(NamedTuple):
    """One artwork download attempt: data URI on success, else why it failed."""

    data: str | None
    outcome: FetchOutcome
    detail: str = ""


class ArtworkRetry:
    """Retry schedule for the artwork URL that is wanted but not downloaded yet."""

    def __init__(self) -> None:
        """Create an idle schedule."""
        self.url: str | None = None
        self.gave_up = False
        self.last_detail = ""
        self._transient_failures = 0
        self._not_found_failures = 0

    def start(self, url: str | None) -> None:
        """Track ``url`` with a fresh budget (None: nothing to retry)."""
        self.url = url
        self.gave_up = False
        self.last_detail = ""
        self._transient_failures = 0
        self._not_found_failures = 0

    def reset(self) -> None:
        """Forget the current URL: downloaded, no longer wanted, or no art at all."""
        self.start(None)

    def record_failure(self, outcome: FetchOutcome, detail: str = "") -> float | None:
        """Register a failed attempt and return the delay before the next one, or None to give up."""
        self.last_detail = detail
        if outcome is FetchOutcome.NOT_FOUND:
            if self._not_found_failures >= len(NOT_FOUND_RETRY_DELAYS):
                self.gave_up = True
                return None
            delay = NOT_FOUND_RETRY_DELAYS[self._not_found_failures]
            self._not_found_failures += 1
        else:
            delay = TRANSIENT_RETRY_DELAYS[min(self._transient_failures, len(TRANSIENT_RETRY_DELAYS) - 1)]
            self._transient_failures += 1
        return delay + random.uniform(0, RETRY_JITTER * delay)  # noqa: S311
