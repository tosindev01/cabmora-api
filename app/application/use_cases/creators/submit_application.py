"""A studio asks to join Flow.

Public and unauthenticated, like the enquiry form — the whole point is that
somebody who has never heard of us can apply. That also makes it the second
unauthenticated write in the API, so the same caution applies: nothing here
trusts the caller, and a duplicate submission is absorbed rather than
multiplying the review queue.
"""

import logging

from app.domain.entities.creator_application import CreatorApplication
from app.application.use_cases.notifications.notifier import Notifier
from app.domain.repositories.creator_application_repository import (
    CreatorApplicationRepository,
)
from app.domain.services.email_sender import EmailSender

logger = logging.getLogger(__name__)


class SubmitCreatorApplication:
    def __init__(
        self,
        applications: CreatorApplicationRepository,
        email: EmailSender,
        notifier: Notifier,
    ) -> None:
        self._applications = applications
        self._email = email
        self._notifier = notifier

    async def execute(
        self,
        *,
        studio_name: str,
        applicant_name: str,
        email: str,
        portfolio_url: str | None,
        discipline: str,
        annual_volume: str,
        storage_needs: str,
        bottleneck: str,
        plan: str,
    ) -> CreatorApplication:
        address = email.strip().lower()

        # Somebody who submits twice gets their first application back rather
        # than a second row. Two entries for one studio means two reviewers
        # can approve it, and approving twice creates two accounts.
        existing = await self._applications.get_pending_by_email(address)
        if existing is not None:
            logger.info("[creators] %s already has an application pending", address)
            return existing

        application = await self._applications.add(
            CreatorApplication(
                studio_name=studio_name.strip(),
                applicant_name=applicant_name.strip(),
                email=address,
                portfolio_url=(portfolio_url or "").strip() or None,
                discipline=discipline.strip(),
                annual_volume=annual_volume.strip(),
                storage_needs=storage_needs.strip(),
                bottleneck=bottleneck.strip(),
                plan=plan.strip(),
            )
        )

        # Nobody was told before this: the applicant got an acknowledgement
        # and the application sat in a table until somebody thought to look.
        await self._notifier.creator_applied(
            studio_name=application.studio_name,
            contact_name=application.applicant_name,
        )

        try:
            await self._email.send_creator_application_received(
                to=application.email,
                first_name=application.applicant_name.split(" ")[0],
                studio_name=application.studio_name,
            )
        except Exception:  # noqa: BLE001
            # The application is recorded. Failing to acknowledge it is a
            # worse experience, not a reason to lose the submission.
            logger.exception(
                "[creators] recorded %s but could not acknowledge it", application.id
            )

        logger.info("[creators] application from %s received", application.studio_name)
        return application
