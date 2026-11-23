"""Throttling repeated failures, in process.

Deliberately small and dependency-free. The obvious library choice keys on the
client IP by default, and behind Railway's router plus this platform's own
nginx the address a request appears to come from is a proxy's, not a person's
— so a stock IP limiter would either throttle every visitor as one bucket or
be bypassed by a forged header. Keying is the decision that matters here, so
it is made explicitly at each call site rather than inherited from a default.

**Only failures are counted, and a success forgets them.** Somebody mistyping
their password twice before getting it right should not be closer to a
lockout than somebody who signed in cleanly.

Known limitation: the window lives in this process's memory. It resets on
deploy, and two replicas would each keep their own. For one container in front
of a small business that is honest protection; the upgrade, if the API is ever
scaled out, is the same interface backed by Redis.
"""

import time
from collections import deque
from dataclasses import dataclass
from threading import Lock

#: Above this many tracked keys, sweep the spent ones. Not a cap — a sweep
#: keeps a burst of one-off keys from accumulating for the process's lifetime.
_SWEEP_THRESHOLD = 4096


@dataclass(frozen=True)
class Budget:
    """How many failures are tolerated, over how long."""

    failures: int
    per_seconds: int


class FailureLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        # Uvicorn runs one event loop per worker, but the threadpool under
        # `run_in_threadpool` is real concurrency; a plain dict mutation is
        # not worth reasoning about twice.
        self._lock = Lock()

    def retry_after(self, key: str, budget: Budget) -> int | None:
        """Seconds until this key may try again, or None if it may now."""
        now = time.monotonic()
        with self._lock:
            recent = self._recent(key, budget, now)
            if len(recent) < budget.failures:
                return None
            # The window slides off the oldest failure still counted.
            return max(1, int(recent[0] + budget.per_seconds - now) + 1)

    def record_failure(self, key: str, budget: Budget) -> None:
        now = time.monotonic()
        with self._lock:
            recent = self._recent(key, budget, now)
            recent.append(now)
            self._hits[key] = recent
            if len(self._hits) > _SWEEP_THRESHOLD:
                self._sweep(budget, now)

    def forget(self, key: str) -> None:
        """Clear the count — called after a success."""
        with self._lock:
            self._hits.pop(key, None)

    # --- internals ---

    def _recent(self, key: str, budget: Budget, now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            return deque()
        cutoff = now - budget.per_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits

    def _sweep(self, budget: Budget, now: float) -> None:
        cutoff = now - budget.per_seconds
        self._hits = {
            key: hits
            for key, hits in self._hits.items()
            if hits and hits[-1] > cutoff
        }
