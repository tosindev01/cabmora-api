import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.observability import init_error_tracking

# Started before the routers are imported, deliberately. The outage this
# repository remembers was a NameError raised while importing `api/deps.py` —
# a crash with no request, no app and nothing watching. A reporter installed
# after that import could not have seen it.
init_error_tracking()

from app.api.v1.routers import (  # noqa: E402 — must follow the line above
    billing,
    admin,
    auth,
    collaboration,
    enquiries,
    enquiries_admin,
    health,
    projects,
    comments,
    creator_studios,
    creators,
    media,
    media_local,
    notifications,
    reviews,
    share_preview,
    sharing,
    stats,
    support,
)
from app.core.config import get_settings
from app.core.exceptions import (
    AuthenticationError,
    ConfigurationError,
    DomainError,
    SchedulingUnavailableError,
    StorageUnavailableError,
    EntityAlreadyExistsError,
    EntityNotFoundError,
    PermissionDeniedError,
    TooManyAttemptsError,
    ValidationError,
)
# Uvicorn configures its own loggers and leaves the root alone, so every
# `logger.info` in this codebase was going nowhere — locally *and* in
# deployment. Only ERROR surfaced, via logging's last-resort handler. That
# hid the email adapter's delivery lines, and made a password reset
# impossible to finish in local development, where the logged link is the
# only copy of it.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)

# --- The response contract -------------------------------------------------
#
# Success: the resource itself, or `Page[T]` for a collection. No envelope.
#
# Failure: ALWAYS `{"detail": "<one human-readable sentence>"}`, whatever went
# wrong — a domain rule, a schema violation, or a crash. Schema failures add
# `errors: [{field, message}]` alongside it so a form can highlight individual
# inputs, but `detail` is a string in every single case.
#
# That invariant is the point. Without it FastAPI puts a *list of objects* in
# `detail` for validation errors, so a client reading `detail` gets a sentence
# from one failure and raw JSON from another — which is exactly what used to
# reach users in an error banner.

EXCEPTION_STATUS_MAP: dict[type[DomainError], int] = {
    EntityNotFoundError: status.HTTP_404_NOT_FOUND,
    EntityAlreadyExistsError: status.HTTP_409_CONFLICT,
    AuthenticationError: status.HTTP_401_UNAUTHORIZED,
    PermissionDeniedError: status.HTTP_403_FORBIDDEN,
    ValidationError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    TooManyAttemptsError: status.HTTP_429_TOO_MANY_REQUESTS,
    ConfigurationError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    # 502: this service is working and the one behind it is not.
    SchedulingUnavailableError: status.HTTP_502_BAD_GATEWAY,
    StorageUnavailableError: status.HTTP_502_BAD_GATEWAY,
}


@asynccontextmanager
def _start_sweeper() -> "asyncio.Task | None":
    """Run the scheduled jobs from inside the API, on a timer.

    These belong on a real cron, and `scripts.run_scheduled` is still the
    thing to point one at. This exists because there was no cron: previews are
    made by a background task fired after an upload, a deploy kills whatever
    is in flight, and the sweep that should catch the remainder was never
    scheduled. Clients sat in front of galleries that said "preparing"
    indefinitely, twice.

    Deliberately modest about what it guarantees. It is a safety net rather
    than a scheduler — if the service is scaled past one container each will
    sweep, which wastes a little work and breaks nothing, since the jobs are
    idempotent and claim what they process. Set `SWEEP_INTERVAL_SECONDS=0` to
    turn it off once a real cron exists.
    """
    interval = get_settings().sweep_interval_seconds
    if interval <= 0:
        return None

    async def loop() -> None:
        from scripts.run_scheduled import main as run_scheduled

        while True:
            # Sleeps first: startup is busy, and anything left over has
            # already been waiting, so a few more minutes costs nothing.
            await asyncio.sleep(interval)
            try:
                await run_scheduled()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                # A sweep that throws must never take the API down with it.
                # `run_scheduled` already isolates its own jobs; this is the
                # backstop for anything it cannot.
                logger.exception("[sweep] run failed — continuing")

    logger.info("[sweep] running scheduled jobs every %ss", interval)
    return asyncio.create_task(loop())


async def _warn_if_google_signin_lapsed() -> None:
    """Say loudly, at boot, if the calendar sign-in needs renewing.

    Nothing can fix this from inside the process: a rejected refresh token
    needs a human to consent again. What the API can do is stop the discovery
    happening the moment somebody tries to confirm a client's call.
    """
    settings = get_settings()
    if settings.meeting_backend != "google":
        return

    from app.domain.services.meeting_scheduler import SchedulerAuthExpired
    from app.infrastructure.scheduling.google_calendar_scheduler import (
        GoogleCalendarScheduler,
    )

    try:
        await GoogleCalendarScheduler(
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            refresh_token=settings.google_refresh_token or "",
            calendar_id=settings.google_calendar_id,
        )._token()
    except SchedulerAuthExpired as exc:
        logger.error("[calendar] %s", exc)
    except Exception:  # noqa: BLE001
        # Google being briefly unreachable at boot is not worth a scary line,
        # and is not what this check is for.
        logger.warning("[calendar] could not verify the Google sign-in at startup")


async def lifespan(app: FastAPI):
    if not get_settings().media_is_configured:
        logger.error(
            "[media] R2 credentials are missing — uploads and delivery are "
            "disabled. Everything else works. Set R2_ACCOUNT_ID, R2_BUCKET, "
            "R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY to enable them."
        )

    # Schema is applied by `alembic upgrade head` before the app starts, not
    # here. Creating tables from the web process races between workers and
    # cannot alter anything that already exists.
    # Checked at boot rather than discovered by an administrator pressing
    # Confirm. A Google sign-in that has lapsed stays lapsed until a person
    # re-authorises, so the sooner it is said out loud the better.
    await _warn_if_google_signin_lapsed()

    sweeper = _start_sweeper()
    try:
        yield
    finally:
        if sweeper is not None:
            sweeper.cancel()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        status_code = EXCEPTION_STATUS_MAP.get(type(exc), status.HTTP_400_BAD_REQUEST)
        # A 429 without Retry-After tells a client it was refused but not when
        # to come back, which is how polite clients end up hammering.
        headers = (
            {"Retry-After": str(exc.retry_after)}
            if isinstance(exc, TooManyAttemptsError)
            else None
        )
        return JSONResponse(
            status_code=status_code, content={"detail": str(exc)}, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Give schema failures the same shape as domain failures."""
        errors = [
            {
                # Drop the leading "body"/"query"/"path" segment: the caller
                # knows where they put it, they need to know which field.
                "field": ".".join(str(part) for part in error["loc"][1:])
                or str(error["loc"][0]),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": errors[0]["message"] if errors else "Invalid request.",
                "errors": errors,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """A crash still answers in the API's own shape.

        The message is deliberately generic. Exception text carries table names,
        file paths and query fragments, and this response goes to the public —
        the detail belongs in the log, which is where it goes.
        """
        logger.exception(
            "Unhandled error on %s %s", request.method, request.url.path
        )
        # No explicit report here. Verified 2026-09-27: the SDK's Starlette
        # integration wraps registered exception handlers and raises its own
        # event for this crash, marked unhandled — which is the more useful
        # of the two. Reporting again from here only sent everything twice.
        # If reports from requests ever stop arriving, this is the first
        # assumption to re-check.
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Something went wrong. Please try again."},
        )

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(enquiries.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(projects.admin_router, prefix="/api/v1")
    app.include_router(media.router, prefix="/api/v1")
    app.include_router(media.assets_router, prefix="/api/v1")
    app.include_router(media.folders_router, prefix="/api/v1")
    app.include_router(media.library_router, prefix="/api/v1")
    app.include_router(comments.router, prefix="/api/v1")
    app.include_router(collaboration.router, prefix="/api/v1")
    app.include_router(creators.router, prefix="/api/v1")
    app.include_router(creators.admin_router, prefix="/api/v1")
    app.include_router(creator_studios.router, prefix="/api/v1")
    app.include_router(media_local.router, prefix="/api/v1")
    app.include_router(projects.router, prefix="/api/v1")
    app.include_router(enquiries_admin.router, prefix="/api/v1")
    app.include_router(billing.admin_router, prefix="/api/v1")
    app.include_router(billing.router, prefix="/api/v1")
    app.include_router(billing.webhook_router, prefix="/api/v1")
    app.include_router(sharing.router, prefix="/api/v1")
    # Unauthenticated, and the only read of anybody's photographs that is.
    app.include_router(sharing.public_router, prefix="/api/v1")
    app.include_router(notifications.router, prefix="/api/v1")
    app.include_router(stats.router, prefix="/api/v1")
    # At the root, not /api/v1: a crawler asks for the share URL itself.
    # nginx proxies /s/ here — see apps/web/nginx.conf.template.
    app.include_router(share_preview.router)
    app.include_router(support.router, prefix="/api/v1")
    app.include_router(support.admin_router, prefix="/api/v1")
    app.include_router(reviews.admin_router, prefix="/api/v1")
    # Public: what real clients said, for the marketing site.
    app.include_router(reviews.public_router, prefix="/api/v1")
    return app


app = create_app()
