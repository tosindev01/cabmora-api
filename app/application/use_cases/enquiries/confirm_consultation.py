"""Cabmora agrees a call the client asked for.

This is the other half of the website's slot picker. A visitor choosing a time
creates a REQUESTED consultation and nothing else — no calendar entry, no
meeting link, no email promising anything. Everything that makes the call real
happens here, when a person has looked at it.

Confirming at a different time is the same action, not a second one. An admin
looking at a requested Thursday they cannot make says "Friday instead", and
two operations would eventually produce the one where the time moved and
nobody told the client.
"""

import logging
from datetime import datetime, timedelta
from uuid import UUID

from app.core.exceptions import (
    DomainError,
    EntityNotFoundError,
    SchedulingUnavailableError,
    ValidationError,
)
from app.domain.entities.consultation import Consultation
from app.domain.entities.enquiry import Enquiry, EnquiryStatus
from app.domain.entities.enquiry_event import EnquiryEvent, EnquiryEventKind
from app.domain.entities.user import User
from app.application.use_cases.notifications.notifier import Notifier
from app.domain.repositories.enquiry_repository import EnquiryRepository
from app.domain.services.email_sender import EmailSender
from app.domain.services.meeting_scheduler import (
    ManualScheduler,
    MeetingScheduler,
    ScheduledMeeting,
    SchedulerAuthExpired,
)

logger = logging.getLogger(__name__)

#: How far either side of a proposed slot to look for a clash.
_MAX_CONSULTATION_HOURS = 4


class ConfirmConsultation:
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
        consultation_id: UUID,
        actor: User,
        *,
        scheduled_at: datetime | None = None,
        duration_minutes: int | None = None,
        meeting_url: str | None = None,
    ) -> Consultation:
        enquiry = await self._enquiries.get_by_id(enquiry_id)
        if enquiry is None:
            raise EntityNotFoundError("Enquiry not found")

        consultation = next(
            (
                c
                for c in await self._enquiries.list_consultations(enquiry_id)
                if c.id == consultation_id
            ),
            None,
        )
        if consultation is None:
            raise EntityNotFoundError("Consultation not found")
        if not consultation.is_live:
            raise ValidationError("That call was cancelled.")
        if consultation.is_confirmed:
            raise ValidationError("That call is already confirmed.")

        if duration_minutes is not None:
            consultation.duration_minutes = duration_minutes
        consultation.confirm(at=scheduled_at)

        await self._refuse_clash(consultation)

        # Only now, once the time is settled, does anything leave this system.
        meeting = await self._schedule_or_fall_back(
            enquiry=enquiry, consultation=consultation, meeting_url=meeting_url
        )
        consultation.meeting_url = meeting.url
        consultation.provider = meeting.provider

        saved = await self._enquiries.update_consultation(consultation)

        if enquiry.can_move_to(EnquiryStatus.CONSULTATION_BOOKED):
            enquiry.status = EnquiryStatus.CONSULTATION_BOOKED
            await self._enquiries.update(enquiry)

        await self._enquiries.add_event(
            EnquiryEvent(
                enquiry_id=enquiry_id,
                kind=EnquiryEventKind.CONSULTATION_BOOKED,
                actor_id=actor.id,
                payload={
                    "scheduled_at": saved.starts_at.isoformat(),
                    "provider": saved.provider.value,
                    # Recorded, because "we moved your call" is the thing a
                    # client remembers and the timeline should be able to
                    # answer for.
                    "moved": scheduled_at is not None,
                },
            )
        )

        await self._tell_the_client(enquiry, saved)
        return saved

    async def _schedule_or_fall_back(
        self, *, enquiry, consultation: Consultation, meeting_url: str | None
    ) -> ScheduledMeeting:
        """Put the call in the diary, or take the link the admin brought.

        The scheduler raises rather than falling back, deliberately: a
        confirmation with no diary entry is worse than one that failed loudly.
        That reasoning holds for a *silent* fallback — somebody believing in a
        meeting nobody scheduled. It does not hold when the admin has typed a
        link themselves, because then they already know there is no calendar
        entry: they made the link.

        So a calendar outage stops being a wall. With a link, the booking goes
        through and is recorded as manual, which is the truth. Without one,
        the refusal says a link is the way past it rather than leaving
        somebody to guess.
        """
        try:
            return await self._scheduler.schedule(
                summary=f"Cabmora consultation — {enquiry.event_type}",
                starts_at=consultation.starts_at,
                minutes=consultation.duration_minutes,
                attendees=[enquiry.email],
                meeting_url=meeting_url,
            )
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            lapsed = isinstance(exc, SchedulerAuthExpired)
            if lapsed:
                logger.error("[consultations] %s", exc)
            else:
                logger.exception(
                    "[consultations] scheduling for enquiry %s failed", enquiry.id
                )

            if meeting_url:
                logger.warning(
                    "[consultations] calendar unavailable — confirming %s with the "
                    "link the administrator supplied",
                    consultation.id,
                )
                return await ManualScheduler().schedule(
                    summary="",
                    starts_at=consultation.starts_at,
                    minutes=consultation.duration_minutes,
                    attendees=[enquiry.email],
                    meeting_url=meeting_url,
                )

            raise SchedulingUnavailableError(
                (
                    "The calendar sign-in has expired, so nothing has been "
                    "confirmed and the slot is still free. Reconnect Google "
                    "Calendar — or paste a meeting link and confirm again, "
                    "which books the call without it."
                )
                if lapsed
                else (
                    "The calendar would not create this meeting, so nothing "
                    "has been confirmed and the slot is still free. Try "
                    "again, or paste a meeting link to book it without the "
                    "calendar."
                )
            ) from exc

    async def _refuse_clash(self, proposed: Consultation) -> None:
        """Checked here as well as in the picker.

        The website only offers free days, but an admin can type any time, two
        of them can be in two tabs, and a requested slot can be confirmed long
        after it was asked for.
        """
        window_start = proposed.starts_at - timedelta(hours=_MAX_CONSULTATION_HOURS)
        others = await self._enquiries.list_consultations_between(
            window_start, proposed.ends_at
        )
        clash = next((c for c in others if proposed.overlaps(c)), None)
        if clash is not None:
            raise ValidationError(
                "That overlaps a call already in the diary. Pick another time."
            )

    async def _tell_the_client(self, enquiry: Enquiry, consultation: Consultation) -> None:
        """Last, and never fatal — the call is confirmed either way.

        Raising here would report a failure for work that is done and invite a
        second confirmation on the retry, which would put a second event in
        somebody's calendar.
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
                "[consultation] %s confirmed for %s; telling %s failed: %r",
                consultation.id,
                consultation.starts_at.isoformat(),
                enquiry.email,
                exc,
            )
