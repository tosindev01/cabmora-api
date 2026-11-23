"""Reporting crashes somewhere a person will actually see them.

Wrapped rather than called directly from `main.py` for two reasons. The
scrubbing below has to happen in exactly one place — this application handles
passwords, session cookies and single-use links, none of which may leave the
building — and the app has to start and run normally for anyone who has not
configured a reporter, which is the default.

Requests need nothing from `report()`: the SDK's Starlette integration wraps
the `Exception` handler in `main.py` and raises its own event, verified
2026-09-27 on both the propagating and the handled path. `report()` exists
for the code that no integration covers — the scheduled worker, which has no
request, no response and nobody watching it fail.
"""

import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_enabled = False

#: Headers that carry credentials. Dropped before anything is sent.
_SECRET_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key", "api-token"}

#: Query parameters that are themselves credentials — a reset or invite link
#: is a working key to an account for as long as it lives.
_SECRET_PARAMS = ("token", "signature", "password")


def init_error_tracking() -> None:
    """Start reporting, if somewhere to report to has been configured."""
    global _enabled
    settings = get_settings()

    if not settings.sentry_dsn:
        logger.info(
            "[observability] no SENTRY_DSN set — crashes go to the log only"
        )
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        # A missing optional dependency must not stop the API serving traffic.
        logger.error("[observability] sentry-sdk is not installed — not reporting")
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.railway_git_commit_sha,
        # Off by default: tracing is a different product from crash reporting
        # and is where the cost is.
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # Never send user identifiers, IP addresses or cookies.
        send_default_pii=False,
        # Request bodies carry passwords on four of this API's endpoints.
        # There is no sampling rate at which that is acceptable.
        max_request_body_size="never",
        # The one that matters most, and the one that is on by default.
        # Sentry attaches every stack frame's local variables, and the frame
        # handling a sign-in holds the request body — so a crash anywhere
        # near `/auth/login` would post a customer's plaintext password to a
        # third party. Verified: with this left at its default, the password,
        # the session cookie and a live reset token all appear in the
        # payload. Losing locals costs some debugging comfort. Keeping them
        # costs credentials.
        include_local_variables=False,
        # Breadcrumbs from log lines, but no *events* from them. Without
        # this, `logger.exception` in the unhandled-error handler raises its
        # own event alongside the one reported below — the same crash twice,
        # at twice the quota.
        integrations=[LoggingIntegration(level=logging.INFO, event_level=None)],
        before_send=_scrub,
    )
    _enabled = True
    logger.info(
        "[observability] reporting crashes for environment=%s release=%s",
        settings.environment,
        settings.railway_git_commit_sha or "unknown",
    )


def report(exc: BaseException) -> None:
    """Send one crash. A no-op when nothing is configured."""
    if not _enabled:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001
        # Reporting an error must never become the error. This runs inside
        # the handler that is already dealing with a crash.
        logger.exception("[observability] could not report a crash")


def _scrub(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    """Strip credentials before an event leaves the process.

    Belt and braces over the `init` options above: those are the SDK's
    promises, and this is ours. A leak here is a password in a third party's
    database, so it is worth saying twice.
    """
    request = event.get("request")
    if isinstance(request, dict):
        # Whatever the SDK decided about bodies, we do not send one.
        request.pop("data", None)

        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                name: value
                for name, value in headers.items()
                if name.lower() not in _SECRET_HEADERS
            }

        request.pop("cookies", None)

        for field in ("query_string", "url"):
            value = request.get(field)
            if isinstance(value, str) and any(p in value.lower() for p in _SECRET_PARAMS):
                request[field] = _redact(value)

    return event


def _redact(value: str) -> str:
    """Keep the shape of a URL or query string, lose the secret in it."""
    parts = []
    for chunk in value.replace("?", "&").split("&"):
        key = chunk.split("=", 1)[0]
        if key.lower() in _SECRET_PARAMS and "=" in chunk:
            parts.append(f"{key}=[redacted]")
        else:
            parts.append(chunk)
    return "&".join(parts)
