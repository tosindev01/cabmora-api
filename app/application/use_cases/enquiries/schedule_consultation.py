import logging
from datetime import datetime, timedelta
from uuid import UUID

from app.core.display import DISPLAY_TZ
from app.core.exceptions import EntityNotFoundError, ValidationError
from app.domain.entities.consultation import Consultation
from app.domain.entities.enquiry import Enquiry, EnquiryStatus
from app.domain.entities.enquiry_event import EnquiryEvent, EnquiryEventKind
from app.domain.entities.user import User
from app.application.use_cases.notifications.notifier import Notifier
from app.domain.repositories.enquiry_repository import EnquiryRepository
from app.domain.services.email_sender import EmailSender
from app.domain.services.meeting_scheduler import MeetingScheduler

logger = logging.getLogger(__name__)

#: How far back the clash window reaches. A call cannot run longer than this, so
#: nothing starting earlier can still be in progress — bounds the query without
#: scanning the table.
_MAX_CONSULTATION_HOURS = 8


class ScheduleConsultation:
    def __init__(
        self,
        enquiries: EnquiryRepository,
        scheduler: MeetingScheduler,
        email: EmailSender,
        notifier: Notifier,
    ) -> None:
        self._enquiries = enquiries
        self._scheduler = scheduler
        self._email = email
        self._notifier = notifier

    async def execute(
        self,
        enquiry_id: UUID,
        actor: User,
        scheduled_at: datetime,
        duration_minutes: int = 30,
        meeting_url: str | None = None,
    ) -> Consultation:
        enquiry = await self._enquiries.get_by_id(enquiry_id)
        if enquiry is None:
            raise EntityNotFoundError("Enquiry not found")
        if enquiry.status in {EnquiryStatus.WON, EnquiryStatus.LOST}:
            raise ValidationError("This enquiry is closed.")
        if duration_minutes <= 0:
            raise ValidationError("A consultation needs a positive duration.")

        proposed = Consultation(
            enquiry_id=enquiry_id,
            scheduled_at=scheduled_at,
            duration_minutes=duration_minutes,
        )

        # Checked here, not only in the UI. The availability grid is a
        # convenience; this is the rule. Two admins booking the same slot in
        # different tabs would both see it free.
        window_start = proposed.starts_at - timedelta(hours=_MAX_CONSULTATION_HOURS)
        clashes = await self._enquiries.list_consultations_between(
            window_start, proposed.ends_at
        )
        clash = next((c for c in clashes if proposed.overlaps(c)), None)
        if clash is not None:
            local = clash.starts_at.astimezone(DISPLAY_TZ)
            raise ValidationError(
                f"That overlaps a consultation already booked at "
                f"{local.strftime('%H:%M')} for {clash.duration_minutes} "
                "minutes. Pick another slot."
            )

        meeting = await self._scheduler.schedule(
            summary=f"Cabmora consultation — {enquiry.event_type}",
            starts_at=scheduled_at,
            minutes=duration_minutes,
            attendees=[enquiry.email],
            meeting_url=meeting_url,
        )

        consultation = await self._enquiries.add_consultation(
            Consultation(
                enquiry_id=enquiry_id,
                scheduled_at=scheduled_at,
                duration_minutes=duration_minutes,
                meeting_url=meeting.url,
                provider=meeting.provider,
                created_by=actor.id,
            )
        )

        # Booking moves the lead along, but only from a stage it may leave —
        # re-booking after a quote should not drag it backwards.
        if enquiry.can_move_to(EnquiryStatus.CONSULTATION_BOOKED):
            enquiry.status = EnquiryStatus.CONSULTATION_BOOKED
            await self._enquiries.update(enquiry)

        await self._enquiries.add_event(
            EnquiryEvent(
                enquiry_id=enquiry_id,
                kind=EnquiryEventKind.CONSULTATION_BOOKED,
                actor_id=actor.id,
                payload={
                    "scheduled_at": scheduled_at.isoformat(),
                    "provider": meeting.provider.value,
                },
            )
        )

        await self._confirm(enquiry, consultation)
        return consultation

    async def _confirm(self, enquiry: Enquiry, consultation: Consultation) -> None:
        """Tell the client the moment the slot is taken.

        Last, and never fatal: the booking, the status move and the timeline
        entry have all happened by now, so raising would report a failure for
        work that is done and invite a duplicate booking on the retry.

        It is also not optional. Without it the first a client hears of a call
        is the reminder half an hour before it — too late to say the time does
        not work, which makes an unannounced booking worse than none.
        """
        # Both sides: the client's own portal, where they have one, and the
        # office — which the email never told, because the booking confirmation
        # is addressed to the client alone.
        await self._notifier.consultation_booked(
            client_email=enquiry.email,
            client_name=enquiry.full_name,
            starts_at=consultation.starts_at,
            enquiry_id=enquiry.id,
        )
        try:
            await self._email.send_consultation_booked(
                to=enquiry.email,
                name=enquiry.full_name,
                starts_at=consultation.starts_at,
                duration_minutes=consultation.duration_minutes,
                meeting_url=consultation.meeting_url,
            )
        except Exception as exc:  # noqa: BLE001 — see docstring
            logger.error(
                "[consultation] %s booked for %s; confirmation to %s failed: %r",
                consultation.id, consultation.starts_at.isoformat(), enquiry.email, exc,
            )
