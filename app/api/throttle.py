"""Where the throttling policy for this API is written down.

One module so the numbers can be read together and argued about, rather than
scattered across routers as literals.

**Keyed by account, not by address.** Behind Railway's router and this
platform's nginx, the address a request appears to arrive from is a proxy's:
keying on it would either lump every visitor into one bucket — throttling
real people who did nothing wrong — or be defeated by a forged
`X-Forwarded-For`. The email in the request body has neither problem. It is
also the thing actually under attack: somebody guessing at the admin account
is stopped whichever address they guess from.

The trade-off, stated plainly: this lets a nuisance lock a *known* address out
of signing in for a few minutes by failing on purpose. That is why the windows
are minutes rather than hours, and why a correct password clears the count
immediately. A distributed attempt spread across many accounts is not caught
here — that needs a shared store and address-level limiting, and is noted in
`docs/ARCHITECTURE.md` rather than half-built.
"""

from app.core.exceptions import TooManyAttemptsError
from app.core.rate_limit import Budget, FailureLimiter

#: Six wrong passwords in five minutes is somebody guessing, not somebody
#: who cannot remember. A person who *has* forgotten is sent to the reset
#: flow by the message rather than left to keep trying.
LOGIN = Budget(failures=6, per_seconds=5 * 60)

#: Reset and invite links carry 32 random bytes, so guessing one is not a
#: strategy. This is here to stop the *volume* rather than the guess.
LINK_REDEMPTION = Budget(failures=10, per_seconds=10 * 60)

#: Asking for a reset link is not a failure — it is counted anyway, because
#: the abuse here is using somebody else's address as a mail target.
RESET_REQUEST = Budget(failures=5, per_seconds=15 * 60)

_limiter = FailureLimiter()


def guard(key: str, budget: Budget, message: str) -> None:
    """Refuse if this key has spent its budget. Call before doing the work."""
    wait = _limiter.retry_after(key, budget)
    if wait is not None:
        raise TooManyAttemptsError(message, retry_after=wait)


def record_failure(key: str, budget: Budget) -> None:
    _limiter.record_failure(key, budget)


def forget(key: str) -> None:
    """Called on success, so honest mistakes do not accumulate."""
    _limiter.forget(key)


def reset() -> None:
    """Forget every count.

    Exists because this module holds process-wide state, which a test suite
    would otherwise carry from one test into the next.
    """
    global _limiter
    _limiter = FailureLimiter()
