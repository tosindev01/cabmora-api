"""Send consultation reminders. Run on a schedule.

    python -m scripts.send_reminders

Designed to be run every few minutes by a scheduler — Railway's cron, or
anything else that can invoke a command. It is safe to run concurrently and
safe to run late: `reminder_sent_at` is stamped per consultation, and the due
window is bounded below by *now* so a job that was down overnight does not wake
up and remind everyone about yesterday.

Exits non-zero only on an unexpected error, so a scheduler's failure alerting
means something.
"""

import asyncio
import logging
import sys

from app.api.deps import get_email_sender
from app.application.use_cases.enquiries.send_reminders import (
    DEFAULT_LEAD_MINUTES,
    SendConsultationReminders,
)
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.enquiry_repository_impl import (
    SqlAlchemyEnquiryRepository,
)
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository
from app.infrastructure.repositories.preferences_repository_impl import (
    SqlAlchemyPreferencesRepository,
)
from app.infrastructure.email.preference_aware_sender import PreferenceAwareEmailSender

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("scripts.send_reminders")


async def main(lead_minutes: int = DEFAULT_LEAD_MINUTES) -> int:
    async with SessionFactory() as session:
        use_case = SendConsultationReminders(
            SqlAlchemyEnquiryRepository(session),
            SqlAlchemyUserRepository(session),
            # Wrapped here too. This job runs outside FastAPI, so it does
            # not get the dependency that does this for a request — and a
            # reminder is exactly the kind of mail somebody turns off.
            PreferenceAwareEmailSender(
                get_email_sender(), SqlAlchemyPreferencesRepository(session)
            ),
        )
        run = await use_case.execute(lead_minutes=lead_minutes)

    if run.considered == 0:
        logger.info("nothing due")
    else:
        logger.info(
            "considered=%d reminded=%d skipped=%d",
            run.considered, run.reminded, run.skipped_no_recipients,
        )
    return 0


if __name__ == "__main__":
    lead = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LEAD_MINUTES
    sys.exit(asyncio.run(main(lead)))
