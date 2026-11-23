"""Generate the watermarked previews waiting to be made.

Run on a schedule, beside `send_reminders`. Every few minutes is plenty: a
client is not standing over the gallery the second an admin finishes uploading,
and a run that finds nothing costs one indexed query.

    python -m scripts.make_renditions
"""

import asyncio
import logging

from app.api.deps import get_image_processor, get_media_storage
from app.application.use_cases.media.generate_renditions import GenerateRenditions
from app.core.config import get_settings
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.media_repository_impl import (
    SqlAlchemyMediaRepository,
)
from app.infrastructure.repositories.project_repository_impl import (
    SqlAlchemyProjectRepository,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("renditions")


async def main() -> None:
    if not get_settings().media_is_configured:
        # Said plainly rather than crashing: the schedule will call this every
        # few minutes forever, and a stack trace on each one buries anything
        # that matters.
        logger.error(
            "Media storage is not configured — no renditions can be made. "
            "Set the R2 variables to enable them."
        )
        return

    async with SessionFactory() as session:
        report = await GenerateRenditions(
            SqlAlchemyMediaRepository(session),
            SqlAlchemyProjectRepository(session),
            get_media_storage(),
            get_image_processor(),
        ).execute()

    if report.processed or report.failed:
        logger.info(
            "%d rendered, %d failed", report.processed, report.failed
        )


if __name__ == "__main__":
    asyncio.run(main())
