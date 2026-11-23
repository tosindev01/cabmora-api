"""Telling the client a call has been put in the diary.

The invariant: the confirmation goes out at booking time, not at reminder time.
A client whose first notice of a call is the message thirty minutes before it
has had no chance to say the slot does not work.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.application.use_cases.enquiries.schedule_consultation import (
    ScheduleConsultation,
)
from app.core.security import hash_password
from app.domain.entities.enquiry import Enquiry
from app.domain.entities.enquiry_event import EnquiryEvent, EnquiryEventKind
from app.domain.entities.user import User, UserRole
from app.domain.services.email_sender import EmailSender
from app.domain.services.meeting_scheduler import ManualScheduler
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.enquiry_repository_impl import (
    SqlAlchemyEnquiryRepository,
)
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository
from tests.conftest import real_notifier


class Recorder(EmailSender):
    def __init__(self, explode: bool = False) -> None:
        self.booked: list[dict] = []
        self.explode = explode

    async def send_invite(self, **kwargs) -> None: ...
    async def send_password_reset(self, **kwargs) -> None: ...
    async def send_gallery_ready(self, **kwargs) -> None: ...
    async def send_creator_application_received(self, **kwargs) -> None: ...
    async def send_creator_approved(self, **kwargs) -> None: ...
    async def send_creator_declined(self, **kwargs) -> None: ...
    async def send_amendment_resolved(self, **kwargs) -> None: ...
    async def send_project_message(self, **kwargs) -> None: ...
    async def send_invoice_issued(self, **kwargs) -> None: ...
    async def send_enquiry_received(self, **kwargs) -> None: ...
    async def send_enquiry_acknowledgement(self, **kwargs) -> None: ...
    async def send_consultation_reminder(self, **kwargs) -> None: ...

    async def send_consultation_booked(self, **kwargs) -> None:
        if self.explode:
            raise RuntimeError("provider down")
        self.booked.append(kwargs)


async def _book(sender, *, at: datetime, minutes: int = 30):
    async with SessionFactory() as session:
        enquiries = SqlAlchemyEnquiryRepository(session)
        lead = Enquiry(
            first_name="Amara",
            last_name="Okafor",
            email="amara@example.com",
            event_type="Wedding",
            message="December coverage.",
        )
        enquiry = await enquiries.add(
            lead,
            EnquiryEvent(enquiry_id=lead.id, kind=EnquiryEventKind.RECEIVED),
        )
        admin = await SqlAlchemyUserRepository(session).add(
            User(
                email=f"admin+{enquiry.id}@x.com",
                first_name="Ada",
                last_name="Lovelace",
                hashed_password=hash_password("password123"),
                role=UserRole.ADMIN,
            )
        )
        await session.commit()
        consultation = await ScheduleConsultation(
            enquiries, ManualScheduler(), sender, real_notifier(session)
        ).execute(enquiry.id, admin, at, minutes)
        await session.commit()
        return enquiry, consultation


@pytest.mark.anyio
async def test_the_client_is_told_at_booking_time(client):
    sender = Recorder()
    at = datetime.now(timezone.utc) + timedelta(days=3)
    enquiry, consultation = await _book(sender, at=at)

    assert len(sender.booked) == 1, "exactly one confirmation, sent immediately"
    sent = sender.booked[0]
    assert sent["to"] == enquiry.email
    assert sent["name"] == enquiry.full_name
    assert sent["duration_minutes"] == consultation.duration_minutes


@pytest.mark.anyio
async def test_the_booking_survives_a_mail_failure(client):
    """The slot is taken before anything is sent, so a dead provider must not
    undo it — a retry would double-book."""
    sender = Recorder(explode=True)
    at = datetime.now(timezone.utc) + timedelta(days=4)
    enquiry, consultation = await _book(sender, at=at)

    async with SessionFactory() as session:
        found = await SqlAlchemyEnquiryRepository(session).list_consultations(enquiry.id)
    assert [c.id for c in found] == [consultation.id]
