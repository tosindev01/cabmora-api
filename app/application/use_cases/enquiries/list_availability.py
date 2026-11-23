from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.core.exceptions import ValidationError
from app.domain.entities.consultation import Consultation
from app.domain.repositories.enquiry_repository import EnquiryRepository

#: A window wider than this is a report, not a booking view, and it would scan
#: far more than an admin can read.
MAX_WINDOW_DAYS = 31


@dataclass(frozen=True)
class BookedSlot:
    """A consultation as the availability grid needs it.

    Carries the enquiry's name so a busy slot says *who* it is with. An admin
    looking at a full Tuesday needs to know whether the 10am is the client they
    are about to call.
    """

    consultation: Consultation
    enquiry_id: UUID
    client_name: str
    event_type: str


class ListAvailability:
    """What is already booked in a window.

    Returns bookings rather than free slots on purpose. "Free" depends on
    working hours, holidays and how long the call needs — decisions that belong
    to whoever is looking at the grid, not to a list endpoint that would have to
    guess them.
    """

    def __init__(self, enquiries: EnquiryRepository) -> None:
        self._enquiries = enquiries

    async def execute(self, *, start: datetime, end: datetime) -> list[BookedSlot]:
        if end <= start:
            raise ValidationError("The window must end after it starts.")
        if end - start > timedelta(days=MAX_WINDOW_DAYS):
            raise ValidationError(
                f"Ask for at most {MAX_WINDOW_DAYS} days at a time."
            )

        booked = await self._enquiries.list_consultations_between(start, end)
        if not booked:
            return []

        # One lookup per enquiry, not per consultation: a client who rebooked
        # three times is one enquiry.
        slots: list[BookedSlot] = []
        seen: dict[UUID, tuple[str, str]] = {}
        for consultation in booked:
            if consultation.enquiry_id not in seen:
                enquiry = await self._enquiries.get_by_id(consultation.enquiry_id)
                seen[consultation.enquiry_id] = (
                    (enquiry.full_name, enquiry.event_type) if enquiry else ("Unknown", "")
                )
            name, event_type = seen[consultation.enquiry_id]
            slots.append(
                BookedSlot(
                    consultation=consultation,
                    enquiry_id=consultation.enquiry_id,
                    client_name=name,
                    event_type=event_type,
                )
            )
        return slots


def day_window(day: datetime) -> tuple[datetime, datetime]:
    """Midnight-to-midnight UTC around a moment. Used by the default view."""
    start = day.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start, start + timedelta(days=1)
