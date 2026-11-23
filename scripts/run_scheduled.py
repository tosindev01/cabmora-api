"""Everything that runs on a timer, in one place.

Railway's cron gives a service one command, so a second scheduled job would
otherwise mean a second always-on container and a second bill. Both jobs here
are short and idempotent, so running them back to back costs one container
start every few minutes instead of two.

Each is isolated: a failing reminder must not stop previews being made, and a
failing rendition must not stop anybody being told about their call. So one
job raising is logged and the next still runs, and the process still exits
non-zero afterwards — Railway marks the run failed, which is the signal worth
having.

    python -m scripts.run_scheduled
"""

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("scheduled")


async def main() -> int:
    from app.core.observability import init_error_tracking, report
    from scripts import make_renditions, send_reminders

    # This process has no user watching it and no request to fail. Without
    # reporting, a worker that breaks looks exactly like one with nothing to
    # do — which is how clients end up staring at galleries that never fill.
    init_error_tracking()

    failures = 0
    for name, job in (
        # Reminders first: a call in thirty minutes is time-critical, a
        # preview is not.
        ("reminders", send_reminders.main),
        ("renditions", make_renditions.main),
    ):
        try:
            await job()
        except Exception as exc:  # noqa: BLE001 — isolation is the point
            failures += 1
            logger.exception("[%s] failed", name)
            report(exc)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
