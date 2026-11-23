import base64
import logging
from datetime import datetime
from uuid import UUID

import httpx

from app.domain.services.email_sender import EmailSender
from app.infrastructure.email.renderer import (
    render_consultation_booked,
    render_consultation_reminder,
    render_enquiry_acknowledgement,
    render_enquiry_received,
    render_invite,
    render_amendment_resolved,
    render_project_message,
    render_creator_application_received,
    render_creator_approved,
    render_creator_declined,
    render_gallery_ready,
    render_invoice_issued,
    render_password_reset,
)

logger = logging.getLogger(__name__)

#: Mailtrap's Email Sending API. Not `sandbox.api.mailtrap.io`, which is the
#: Testing product and delivers to a fake inbox nobody reads.
SEND_URL = "https://send.api.mailtrap.io/api/send"

#: Long enough for a slow API, short enough that an admin creating a customer
#: is not left staring at a spinner because a third party is having a bad day.
TIMEOUT_SECONDS = 10.0


class MailtrapEmailSender(EmailSender):
    """Delivers through Mailtrap's Email Sending API.

    Composition happens in `renderer.py`; this class only knows how to put a
    rendered message on the wire. Swapping provider means another class here and
    no change to any use case — the point of the port.

    **Failures are logged, not raised.** By the time an invite is sent the
    account already exists and the token is already issued, so raising would
    fail a request whose side effects have happened and leave the admin with an
    account they think was never made. The invite URL is logged at ERROR and
    also returned in the API response, so a failed send is recoverable by
    copying the link — which is exactly how the flow works today with the
    logging sender.
    """

    def __init__(
        self,
        *,
        api_token: str,
        sender_email: str,
        sender_name: str,
        support_email: str,
        admin_base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = api_token
        self._sender = {"email": sender_email, "name": sender_name}
        #: Where a reply goes and what the footer prints. Not `sender_email`:
        #: while that is a demo or stand-in domain, a reply following the From
        #: address would reach nobody.
        self._support_email = support_email
        #: Used to deep-link a notification to the lead. None omits the button.
        self._admin_base_url = admin_base_url
        #: Injected in tests. None means one is created per send, which is fine
        #: at these volumes and avoids a client outliving the event loop.
        self._client = client

    async def _post(self, payload: dict) -> None:
        headers = {
            "Api-Token": self._token,
            "Content-Type": "application/json",
        }
        if self._client is not None:
            response = await self._client.post(SEND_URL, json=payload, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.post(SEND_URL, json=payload, headers=headers)
        response.raise_for_status()

    async def _deliver(
        self,
        *,
        to: str,
        message,
        category: str,
        recovery: str,
        attachment: tuple[str, bytes, str] | None = None,
    ) -> None:
        """One send path, so every message gets the same failure handling."""
        payload = {
            "from": self._sender,
            "to": [{"email": to}],
            # Several of these messages ask for a reply. Without this the reply
            # follows the From address, which is only the right mailbox by
            # coincidence.
            "reply_to": {"email": self._support_email},
            "subject": message.subject,
            "html": message.html,
            "text": message.text,
            "category": category,
        }
        if attachment is not None:
            filename, data, content_type = attachment
            payload["attachments"] = [
                {
                    "filename": filename,
                    "content": base64.b64encode(data).decode(),
                    "type": content_type,
                    "disposition": "attachment",
                }
            ]
        try:
            await self._post(payload)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "[email:%s] Mailtrap rejected the message to %s: %s %s. %s",
                category, to, exc.response.status_code, exc.response.text[:400], recovery,
            )
        except httpx.HTTPError as exc:
            logger.error(
                "[email:%s] could not reach Mailtrap for %s: %s. %s",
                category, to, exc, recovery,
            )
        else:
            logger.info("[email:%s] delivered to %s", category, to)

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
        message_body = render_enquiry_received(
            name=name,
            email=email,
            phone=phone,
            event_type=event_type,
            event_date=event_date,
            message=message,
            admin_url=(
                f"{self._admin_base_url.rstrip('/')}/admin/enquiries/{enquiry_id}"
                if self._admin_base_url
                else None
            ),
            support_email=self._support_email,
        )
        await self._deliver(
            to=to,
            message=message_body,
            category="enquiry-received",
            # The lead is already saved; a failed notification loses nothing but
            # the nudge, so the id is enough to find it.
            recovery=f"Enquiry {enquiry_id} is in the console regardless.",
        )

    async def send_enquiry_acknowledgement(
        self, *, to: str, name: str, event_type: str
    ) -> None:
        await self._deliver(
            to=to,
            message=render_enquiry_acknowledgement(
                name=name, event_type=event_type, support_email=self._support_email
            ),
            category="enquiry-ack",
            recovery="",
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
        message = render_consultation_reminder(
            first_name=recipient_first_name,
            with_name=with_name,
            starts_at=starts_at,
            duration_minutes=duration_minutes,
            meeting_url=meeting_url,
            support_email=self._support_email,
        )
        # No recovery hint: unlike an invite there is nothing to copy by hand,
        # and the call happens whether or not the reminder arrived.
        await self._deliver(to=to, message=message, category="reminder", recovery="")

    async def send_consultation_booked(
        self,
        *,
        to: str,
        name: str,
        starts_at: datetime,
        duration_minutes: int,
        meeting_url: str | None,
    ) -> None:
        message = render_consultation_booked(
            name=name,
            starts_at=starts_at,
            duration_minutes=duration_minutes,
            meeting_url=meeting_url,
            support_email=self._support_email,
        )
        await self._deliver(
            to=to,
            message=message,
            category="consultation-booked",
            # The admin booked the slot and can see it; if this never lands the
            # loss is the client's knowledge of it, which no id in a log fixes.
            recovery="The consultation is booked regardless — confirm by hand.",
        )

    async def send_password_reset(self, *, to: str, first_name: str, reset_url: str) -> None:
        message = render_password_reset(
            first_name=first_name,
            reset_url=reset_url,
            support_email=self._support_email,
        )
        await self._deliver(
            to=to,
            message=message,
            category="password_reset",
            # No link in the recovery line. A failed reset is recoverable by
            # asking again from the sign-in page, and a working reset link
            # sitting in an application log is a credential in a log.
            recovery="The person can request another from the sign-in page.",
        )

    async def send_creator_application_received(
        self, *, to: str, first_name: str, studio_name: str
    ) -> None:
        await self._deliver(
            to=to,
            message=render_creator_application_received(
                first_name=first_name,
                studio_name=studio_name,
                support_email=self._support_email,
            ),
            category="creator_application_received",
            recovery=f"{studio_name} applied and was not acknowledged.",
        )

    async def send_creator_approved(
        self, *, to: str, first_name: str, studio_name: str, setup_url: str
    ) -> None:
        await self._deliver(
            to=to,
            message=render_creator_approved(
                first_name=first_name,
                studio_name=studio_name,
                setup_url=setup_url,
                support_email=self._support_email,
            ),
            category="creator_approved",
            # No link in the recovery line: that URL sets a password on a real
            # account, and a working credential in an application log is a
            # credential in a log. The console shows it to the admin instead.
            recovery=f"{studio_name} was approved but not told. Resend from the console.",
        )

    async def send_creator_declined(
        self, *, to: str, first_name: str, studio_name: str
    ) -> None:
        await self._deliver(
            to=to,
            message=render_creator_declined(
                first_name=first_name,
                studio_name=studio_name,
                support_email=self._support_email,
            ),
            category="creator_declined",
            recovery=f"{studio_name} was declined and not told.",
        )

    async def send_gallery_ready(
        self,
        *,
        to: str,
        first_name: str,
        project_title: str,
        photo_count: int,
        gallery_url: str,
        note: str | None = None,
        hands_over_originals: bool = False,
    ) -> None:
        await self._deliver(
            to=to,
            message=render_gallery_ready(
                first_name=first_name,
                project_title=project_title,
                photo_count=photo_count,
                gallery_url=gallery_url,
                note=note,
                hands_over_originals=hands_over_originals,
                support_email=self._support_email,
            ),
            category="gallery_ready",
            recovery=f"Gallery link: {gallery_url}",
        )

    async def send_project_message(
        self,
        *,
        to: str,
        recipient_first_name: str,
        from_name: str,
        project_title: str,
        body: str,
        url: str,
        about_a_photograph: bool = False,
    ) -> None:
        await self._deliver(
            to=to,
            message=render_project_message(
                recipient_first_name=recipient_first_name,
                from_name=from_name,
                project_title=project_title,
                body=body,
                url=url,
                about_a_photograph=about_a_photograph,
                support_email=self._support_email,
            ),
            category="project_message",
            recovery=f"Message link: {url}",
        )

    async def send_amendment_resolved(
        self,
        *,
        to: str,
        first_name: str,
        project_title: str,
        request: str,
        gallery_url: str,
    ) -> None:
        await self._deliver(
            to=to,
            message=render_amendment_resolved(
                first_name=first_name,
                project_title=project_title,
                request=request,
                gallery_url=gallery_url,
                support_email=self._support_email,
            ),
            category="amendment_resolved",
            recovery=f"Gallery link: {gallery_url}",
        )

    async def send_invoice_issued(
        self,
        *,
        to: str,
        first_name: str,
        project_title: str,
        number: str,
        amount: str,
        due_at: datetime,
        invoice_url: str,
        document: tuple[str, bytes, str] | None = None,
        bank=None,
    ) -> None:
        await self._deliver(
            to=to,
            message=render_invoice_issued(
                first_name=first_name,
                project_title=project_title,
                number=number,
                amount=amount,
                due_at=due_at,
                invoice_url=invoice_url,
                bank=bank,
                support_email=self._support_email,
            ),
            category="invoice_issued",
            # Named rather than linked: an unsent invoice is chased by a
            # person, and they need the number, not a URL.
            recovery=f"Invoice {number} was not delivered to {to}.",
            attachment=document,
        )

    async def send_invite(self, *, to: str, first_name: str, invite_url: str) -> None:
        message = render_invite(
            first_name=first_name,
            invite_url=invite_url,
            support_email=self._support_email,
        )
        await self._deliver(
            to=to,
            message=message,
            category="invite",
            recovery=f"Invite link (send manually if needed): {invite_url}",
        )
