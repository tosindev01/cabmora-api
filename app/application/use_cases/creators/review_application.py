"""Approve or decline a studio's application to join Flow.

Approving is the only place in the system that creates a `creator`, so it is
deliberately an administrator's act and nobody else's. Declining is recorded
rather than deleted: the question a second reviewer asks about a familiar
studio name is "did we already say no, and why".
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from app.application.use_cases.invites.provision_account import ProvisionAccount
from app.core.exceptions import EntityNotFoundError, ValidationError
from app.domain.entities.creator_application import CreatorApplication
from app.domain.entities.user import User, UserRole
from app.domain.repositories.creator_application_repository import (
    CreatorApplicationRepository,
)
from app.domain.services.email_sender import EmailSender

logger = logging.getLogger(__name__)

@dataclass
class ApprovalResult:
    application: CreatorApplication
    #: The single-use link the studio needs. Returned once so the console can
    #: fall back to it if the email did not arrive; the router decides whether
    #: it is safe to show, and outside local it is not.
    setup_url: str


class ReviewCreatorApplication:
    def __init__(
        self,
        applications: CreatorApplicationRepository,
        provision: ProvisionAccount,
        email: EmailSender,
    ) -> None:
        self._applications = applications
        self._provision = provision
        self._email = email

    async def approve(self, *, application_id: UUID, actor: User) -> ApprovalResult:
        application = await self._get(application_id)
        # Checked here as well as on the entity. Provisioning runs first so a
        # failure leaves the application pending — but that ordering means a
        # second approval would otherwise be refused by the *account* layer,
        # with "an account with this email already exists", which tells a
        # reviewer nothing about what they actually did wrong.
        if application.is_decided:
            raise ValidationError(
                f"This application was already {application.status.value}."
            )

        # Split on the space rather than asking for two fields: the form asks
        # for "Lead creator / applicant name" as one box, and inventing a
        # surname the applicant never typed would be worse than an empty one.
        first, _, last = application.applicant_name.strip().partition(" ")

        # Provisioning first. If the account cannot be created — usually
        # because that address already has one — the application stays
        # pending and can be dealt with, rather than being marked approved
        # with nothing behind it.
        provisioned = await self._provision.execute(
            email=application.email,
            first_name=first,
            last_name=last,
            # The link's destination follows from the role — Flow's own
            # setup page, per `INVITE_PATHS`.
            role=UserRole.CREATOR,
        )

        application.approve(actor.id, provisioned.user.id)
        saved = await self._applications.update(application)

        try:
            await self._email.send_creator_approved(
                to=application.email,
                first_name=first,
                studio_name=application.studio_name,
                setup_url=provisioned.invite_url,
            )
        except Exception:  # noqa: BLE001
            # The account exists and the link is in `invite_url`, which the
            # console shows — an admin can pass it on by hand.
            logger.exception(
                "[creators] approved %s but could not email %s",
                application.id, application.email,
            )

        logger.info(
            "[creators] %s approved — creator account %s",
            application.studio_name, provisioned.user.id,
        )
        return ApprovalResult(application=saved, setup_url=provisioned.invite_url)

    async def decline(
        self, *, application_id: UUID, actor: User, note: str | None = None
    ) -> CreatorApplication:
        application = await self._get(application_id)
        application.decline(actor.id, note)
        saved = await self._applications.update(application)

        try:
            await self._email.send_creator_declined(
                to=application.email,
                first_name=application.applicant_name.split(" ")[0],
                studio_name=application.studio_name,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[creators] declined %s but could not tell %s",
                application.id, application.email,
            )
        return saved

    async def _get(self, application_id: UUID) -> CreatorApplication:
        application = await self._applications.get_by_id(application_id)
        if application is None:
            raise EntityNotFoundError("Application not found")
        return application
