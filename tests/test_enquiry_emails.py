"""Notifications when a lead arrives.

The rule that matters: a mail provider having a bad afternoon must never turn a
captured lead into a lost one.
"""

import pytest

from app.application.use_cases.enquiries.submit_enquiry import SubmitEnquiry
from app.domain.services.email_sender import EmailSender
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.enquiry_repository_impl import (
    SqlAlchemyEnquiryRepository,
)
from tests.conftest import real_notifier


class Recorder(EmailSender):
    def __init__(self, explode: bool = False) -> None:
        self.sent: list[tuple[str, str]] = []
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
    async def send_consultation_reminder(self, **kwargs) -> None: ...
    async def send_consultation_booked(self, **kwargs) -> None: ...

    async def send_enquiry_received(self, *, to, **kwargs) -> None:
        if self.explode:
            raise RuntimeError("provider down")
        self.sent.append(("received", to))

    async def send_enquiry_acknowledgement(self, *, to, **kwargs) -> None:
        if self.explode:
            raise RuntimeError("provider down")
        self.sent.append(("ack", to))


async def _submit(sender, notify="leads@cabmoramedia.com"):
    async with SessionFactory() as session:
        return await SubmitEnquiry(
            SqlAlchemyEnquiryRepository(session),
            sender,
            real_notifier(session),
            notify,
        ).execute(
            first_name="Amara",
            last_name="Okafor",
            email="Amara@Example.com",
            event_type="Wedding",
            message="Full day coverage in December.",
        )


@pytest.mark.anyio
async def test_both_sides_are_told(client):
    sender = Recorder()
    await _submit(sender)
    assert sorted(sender.sent) == [
        ("ack", "amara@example.com"),
        ("received", "leads@cabmoramedia.com"),
    ], "the client is acknowledged and the pipeline is notified"


@pytest.mark.anyio
async def test_the_lead_survives_a_mail_failure(client):
    """The whole point: the enquiry is saved before anything is sent."""
    sender = Recorder(explode=True)
    saved = await _submit(sender)

    async with SessionFactory() as session:
        found = await SqlAlchemyEnquiryRepository(session).get_by_id(saved.id)
    assert found is not None, "a provider outage must not lose the lead"
    assert found.email == "amara@example.com"


@pytest.mark.anyio
async def test_no_notification_address_still_acknowledges_the_client(client):
    sender = Recorder()
    await _submit(sender, notify=None)
    assert sender.sent == [("ack", "amara@example.com")]


@pytest.mark.anyio
async def test_the_public_endpoint_still_returns_201_when_mail_fails(client, monkeypatch):
    """A visitor must never see a 500 because email is down."""
    from app.api import deps

    monkeypatch.setattr(deps, "get_email_sender", lambda: Recorder(explode=True))
    resp = await client.post("/api/v1/enquiries", json={
        "first_name": "Broken", "last_name": "Mail", "email": "broken@example.com",
        "event_type": "Wedding", "message": "Should still be saved.",
    })
    assert resp.status_code == 201, resp.text
