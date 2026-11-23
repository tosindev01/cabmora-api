"""Consultation reminders.

The properties that matter for a job that runs every few minutes forever:
it must not double-send, it must not remind about the past, and being late must
mean "late" rather than "never".
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.application.use_cases.enquiries.send_reminders import SendConsultationReminders
from app.core.security import hash_password
from app.domain.entities.user import User, UserRole
from app.domain.services.email_sender import EmailSender
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.enquiry_repository_impl import (
    SqlAlchemyEnquiryRepository,
)
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

PASSWORD = "password123"


class RecordingSender(EmailSender):
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_invite(self, *, to, first_name, invite_url) -> None: ...

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

    async def send_consultation_booked(self, **kwargs) -> None: ...

    async def send_consultation_reminder(
        self, *, to, recipient_first_name, with_name, starts_at, duration_minutes, meeting_url
    ) -> None:
        self.sent.append({"to": to, "with": with_name, "name": recipient_first_name})


class ExplodingSender(RecordingSender):
    async def send_consultation_reminder(self, **kwargs) -> None:
        raise RuntimeError("provider down")


async def _admin() -> User:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).add(
            User(email="admin@x.com", first_name="Ada", last_name="Lovelace",
                 hashed_password=hash_password(PASSWORD), role=UserRole.ADMIN)
        )
        await session.commit()
        return user


async def _login(client, email: str) -> None:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text


async def _booked(client, at: datetime, minutes: int = 30) -> str:
    resp = await client.post("/api/v1/enquiries", json={
        "first_name": "Amara", "last_name": "Okafor", "email": "amara@example.com",
        "event_type": "Wedding", "message": "December coverage.",
    })
    enquiry_id = resp.json()["id"]
    booked = await client.post(
        f"/api/v1/admin/enquiries/{enquiry_id}/consultations",
        json={"scheduled_at": at.isoformat(), "duration_minutes": minutes},
    )
    assert booked.status_code == 201, booked.text
    return enquiry_id


async def _run(sender, now: datetime, lead: int = 30):
    async with SessionFactory() as session:
        return await SendConsultationReminders(
            SqlAlchemyEnquiryRepository(session),
            SqlAlchemyUserRepository(session),
            sender,
        ).execute(lead_minutes=lead, now=now)


@pytest.mark.anyio
async def test_both_parties_are_reminded_once(client):
    admin = await _admin()
    await _login(client, admin.email)
    now = datetime.now(timezone.utc)
    await _booked(client, now + timedelta(minutes=20))

    sender = RecordingSender()
    run = await _run(sender, now)

    assert run.reminded == 1
    assert len(sender.sent) == 2, "the client and whoever owns the lead"
    recipients = {m["to"] for m in sender.sent}
    assert recipients == {"amara@example.com", "admin@x.com"}
    # Each side is told who the call is *with*, not their own name back.
    by_to = {m["to"]: m for m in sender.sent}
    assert by_to["amara@example.com"]["with"] == "Cabmora"
    assert by_to["admin@x.com"]["with"] == "Amara Okafor"
    assert by_to["admin@x.com"]["name"] == "Ada"


@pytest.mark.anyio
async def test_running_again_sends_nothing(client):
    """The property that makes a five-minute cron safe."""
    admin = await _admin()
    await _login(client, admin.email)
    now = datetime.now(timezone.utc)
    await _booked(client, now + timedelta(minutes=20))

    first = RecordingSender()
    await _run(first, now)
    assert len(first.sent) == 2

    second = RecordingSender()
    run = await _run(second, now + timedelta(minutes=5))
    assert run.considered == 0
    assert second.sent == [], "a second run must not remind anyone again"


@pytest.mark.anyio
async def test_a_call_further_out_is_not_reminded_yet(client):
    admin = await _admin()
    await _login(client, admin.email)
    now = datetime.now(timezone.utc)
    await _booked(client, now + timedelta(hours=3))

    sender = RecordingSender()
    assert (await _run(sender, now)).considered == 0
    assert sender.sent == []


@pytest.mark.anyio
async def test_a_call_that_already_started_is_not_reminded(client):
    """Without a lower bound, a job that was down overnight would wake up and
    remind everyone about yesterday."""
    admin = await _admin()
    await _login(client, admin.email)
    now = datetime.now(timezone.utc)
    await _booked(client, now - timedelta(minutes=10))

    sender = RecordingSender()
    assert (await _run(sender, now)).considered == 0
    assert sender.sent == []


@pytest.mark.anyio
async def test_a_late_run_still_sends(client):
    """Late is better than never — the window, not an exact lead time."""
    admin = await _admin()
    await _login(client, admin.email)
    now = datetime.now(timezone.utc)
    await _booked(client, now + timedelta(minutes=4))

    sender = RecordingSender()
    assert (await _run(sender, now)).reminded == 1


@pytest.mark.anyio
async def test_a_cancelled_call_is_not_reminded(client):
    admin = await _admin()
    await _login(client, admin.email)
    now = datetime.now(timezone.utc)
    enquiry_id = await _booked(client, now + timedelta(minutes=20))

    async with SessionFactory() as session:
        repo = SqlAlchemyEnquiryRepository(session)
        from uuid import UUID

        booked = await repo.list_consultations(UUID(enquiry_id))
        from app.infrastructure.models.enquiry import ConsultationModel

        model = await session.get(ConsultationModel, str(booked[0].id))
        model.cancelled_at = datetime.now(timezone.utc)
        await session.commit()

    sender = RecordingSender()
    assert (await _run(sender, now)).considered == 0
