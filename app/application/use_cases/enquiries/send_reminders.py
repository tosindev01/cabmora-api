import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.repositories.enquiry_repository import EnquiryRepository
from app.domain.repositories.user_repository import UserRepository
from app.domain.services.email_sender import EmailSender

logger = logging.getLogger(__name__)

#: How far ahead to remind. Thirty minutes is enough to find a quiet room and
#: not so far that the reminder is forgotten before the call.
DEFAULT_LEAD_MINUTES = 30


@dataclass
class ReminderRun:
    considered: int
    reminded: int
    skipped_no_recipients: int


class SendConsultationReminders:
    """Remind both parties that a call is about to start.

    Run by a scheduler, not by a request. Everything it needs to be safe under
    repetition lives in the data: `reminder_sent_at` is stamped per
    consultation, so running every five minutes sends one reminder, and two
    overlapping runs cannot double-send the same row.

    **A consultation is stamped even when the email fails.** The alternative is
    retrying a permanently undeliverable address every five minutes forever. The
    sender logs failures loudly, and a missed reminder is a small harm next to a
    job that never drains.
    """

    def __init__(
        self,
        enquiries: EnquiryRepository,
        users: UserRepository,
        email: EmailSender,
    ) -> None:
        self._enquiries = enquiries
        self._users = users
        self._email = email

    async def execute(
        self, *, lead_minutes: int = DEFAULT_LEAD_MINUTES, now: datetime | None = None
    ) -> ReminderRun:
        moment = now or datetime.now(timezone.utc)
        due = await self._enquiries.list_consultations_awaiting_reminder(
            moment, lead_minutes
        )
        reminded = 0
        skipped = 0

        for consultation in due:
            enquiry = await self._enquiries.get_by_id(consultation.enquiry_id)
            if enquiry is None:
                # The enquiry is gone; nothing to remind anyone about. Stamp it
                # so the job stops reconsidering it every run.
                await self._enquiries.mark_reminder_sent(consultation.id, moment)
                skipped += 1
                continue

            # The client, by the name and address they gave us.
            # The stored first name, not the first word of a full name: "Mary Jane
            # Smith" is not called Mary.
            client_first = enquiry.first_name.strip() or "there"
            await self._email.send_consultation_reminder(
                to=enquiry.email,
                recipient_first_name=client_first,
                with_name="Cabmora",
                starts_at=consultation.starts_at,
                duration_minutes=consultation.duration_minutes,
                meeting_url=consultation.meeting_url,
            )

            # Whoever owns the lead. `assigned_to` first — the person who booked
            # it may have been covering for someone.
            staff_id = enquiry.assigned_to or consultation.created_by
            if staff_id is not None:
                staff = await self._users.get_by_id(staff_id)
                if staff is not None:
                    await self._email.send_consultation_reminder(
                        to=staff.email,
                        recipient_first_name=staff.first_name,
                        with_name=enquiry.full_name,
                        starts_at=consultation.starts_at,
                        duration_minutes=consultation.duration_minutes,
                        meeting_url=consultation.meeting_url,
                    )

            await self._enquiries.mark_reminder_sent(consultation.id, moment)
            reminded += 1

        if due:
            logger.info(
                "[reminders] considered=%d reminded=%d skipped=%d",
                len(due), reminded, skipped,
            )
        return ReminderRun(
            considered=len(due), reminded=reminded, skipped_no_recipients=skipped
        )
