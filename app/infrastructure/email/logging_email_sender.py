import logging
from datetime import datetime
from uuid import UUID

from app.domain.services.email_sender import EmailSender

logger = logging.getLogger(__name__)


class LoggingEmailSender(EmailSender):
    """Writes the message to the log instead of delivering it.

    TODO(mailtrap): replace with `MailtrapEmailSender` implementing the same
    port. Nothing else changes — `get_email_sender` in api/deps.py picks the
    implementation, and no use case knows which one it got.

    Until then this is how an invite link reaches a developer: it is printed,
    not sent. That is fine locally and is exactly why the invite flow must not
    be relied on in production before Mailtrap is wired.
    """

    async def send_invite(self, *, to: str, first_name: str, invite_url: str) -> None:
        logger.info(
            "[email:invite] to=%s name=%s url=%s (not delivered — logging sender)",
            to,
            first_name,
            invite_url,
        )

    async def send_password_reset(self, *, to: str, first_name: str, reset_url: str) -> None:
        # The URL is logged in full on purpose: with no provider wired, this
        # log is the only way to finish a reset in local development.
        logger.info(
            "[email:password_reset] to=%s name=%s url=%s (not delivered — logging sender)",
            to,
            first_name,
            reset_url,
        )

    async def send_creator_application_received(
        self, *, to, first_name, studio_name
    ) -> None:
        logger.info(
            "[email:creator_application_received] to=%s studio=%s "
            "(not delivered — logging sender)", to, studio_name,
        )

    async def send_creator_approved(
        self, *, to, first_name, studio_name, setup_url
    ) -> None:
        # The URL in full: with no provider wired, this log is the only way to
        # finish an approval in local development.
        logger.info(
            "[email:creator_approved] to=%s studio=%s url=%s "
            "(not delivered — logging sender)", to, studio_name, setup_url,
        )

    async def send_creator_declined(self, *, to, first_name, studio_name) -> None:
        logger.info(
            "[email:creator_declined] to=%s studio=%s (not delivered — logging sender)",
            to, studio_name,
        )

    async def send_gallery_ready(
        self,
        *,
        to,
        first_name,
        project_title,
        photo_count,
        gallery_url,
        note=None,
        hands_over_originals=False,
    ) -> None:
        logger.info(
            "[email:gallery_ready] to=%s project=%s photos=%s url=%s note=%s "
            "(not delivered — logging sender)",
            to, project_title, photo_count, gallery_url, bool(note),
        )

    async def send_project_message(
        self, *, to, recipient_first_name, from_name, project_title, body, url,
        about_a_photograph=False,
    ) -> None:
        logger.info(
            "[email:project_message] to=%s from=%s project=%s "
            "(not delivered — logging sender)",
            to, from_name, project_title,
        )

    async def send_amendment_resolved(
        self, *, to, first_name, project_title, request, gallery_url
    ) -> None:
        logger.info(
            "[email:amendment_resolved] to=%s project=%s request=%.60r "
            "(not delivered — logging sender)",
            to, project_title, request,
        )

    async def send_invoice_issued(
        self, *, to, first_name, project_title, number, amount, due_at,
        invoice_url, document=None, bank=None) -> None:
        logger.info(
            "[email:invoice_issued] to=%s invoice=%s amount=%s due=%s pdf=%s "
            "(not delivered — logging sender)",
            to, number, amount, due_at,
            f"{len(document[1]):,}B" if document else "none",
        )

    async def send_consultation_reminder(
        self,
        *,
        to: str,
        recipient_first_name: str,
        with_name: str,
        starts_at: datetime,
        duration_minutes: int,
        meeting_url: str | None,
    ) -> None:
        logger.info(
            "[email:reminder] to=%s with=%s at=%s (%s min) url=%s "
            "(not delivered — logging sender)",
            to,
            with_name,
            starts_at.isoformat(),
            duration_minutes,
            meeting_url or "none",
        )

    async def send_enquiry_received(
        self,
        *,
        to: str,
        name: str,
        email: str,
        phone: str | None,
        event_type: str,
        event_date: datetime | None,
        message: str,
        enquiry_id: UUID,
    ) -> None:
        logger.info(
            "[email:enquiry-received] to=%s from=%s <%s> type=%s id=%s "
            "(not delivered — logging sender)",
            to, name, email, event_type, enquiry_id,
        )

    async def send_enquiry_acknowledgement(
        self, *, to: str, name: str, event_type: str
    ) -> None:
        logger.info(
            "[email:enquiry-ack] to=%s name=%s type=%s (not delivered — logging sender)",
            to, name, event_type,
        )

    async def send_consultation_booked(
        self,
        *,
        to: str,
        name: str,
        starts_at: datetime,
        duration_minutes: int,
        meeting_url: str | None,
    ) -> None:
        logger.info(
            "[email:consultation-booked] to=%s at=%s (%s min) url=%s "
            "(not delivered — logging sender)",
            to, starts_at.isoformat(), duration_minutes, meeting_url or "none",
        )
