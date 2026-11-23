import asyncio
import logging
from datetime import datetime
from uuid import UUID

from app.domain.entities.consultation import Consultation, ConsultationStatus
from app.domain.entities.enquiry import Enquiry
from app.domain.entities.enquiry_event import EnquiryEvent, EnquiryEventKind
from app.application.use_cases.notifications.notifier import Notifier
from app.domain.repositories.enquiry_repository import EnquiryRepository
from app.domain.services.email_sender import EmailSender

logger = logging.getLogger(__name__)


class SubmitEnquiry:
    """Take a lead from the public form and tell both sides it landed.

    The enquiry is saved first and the emails go afterwards, concurrently. That
    ordering is the point: a lead that is stored but unannounced is recoverable
    from the console, whereas one that failed to save because a mail provider
    was slow is gone, and the person who wrote it has already seen a thank-you.

    `notify_email` is optional. Unset means nobody is told a lead arrived, which
    is the current production state and worth making obvious rather than
    silently skipping.
    """

    def __init__(
        self,
        enquiries: EnquiryRepository,
        email: EmailSender,
        notifier: Notifier,
        notify_email: str | None = None,
    ) -> None:
        self._enquiries = enquiries
        self._email = email
        self._notifier = notifier
        self._notify_email = notify_email

    async def execute(
        self,
        first_name: str,
        last_name: str,
        email: str,
        event_type: str,
        message: str,
        phone: str | None = None,
        whatsapp: str | None = None,
        event_date: datetime | None = None,
        preferred_slot: datetime | None = None,
        customer_id: UUID | None = None,
    ) -> Enquiry:
        # `customer_id` is set when a signed-in client submits this, and is
        # the difference between "a second shoot for Mary Watson" and "a
        # stranger who typed Mary's email address".
        #
        # It is not derived from the email. A client signed in as
        # sam@gmail.com who types sam@work.com into the form is the same
        # person, and matching on the address alone would give them a second
        # account and a second invite — which is the bug this closes.
        enquiry = Enquiry(
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            email=email.lower(),
            event_type=event_type,
            message=message,
            phone=phone,
            whatsapp=whatsapp,
            event_date=event_date,
            customer_id=customer_id,
        )
        saved = await self._enquiries.add(
            enquiry,
            EnquiryEvent(
                enquiry_id=enquiry.id,
                kind=EnquiryEventKind.RECEIVED,
                # No actor: the public submitted this, nobody on staff did.
                payload={"event_type": enquiry.event_type},
            ),
        )
        if preferred_slot is not None:
            await self._request_slot(saved, preferred_slot)

        await self._notify(saved)
        return saved

    async def _request_slot(self, enquiry: Enquiry, when: datetime) -> None:
        """Record the time the visitor asked for.

        A request, not a booking: no calendar entry and no meeting link, and
        the lead does not move to CONSULTATION_BOOKED. Cabmora confirming it
        is what makes it real — see `ConsultationStatus`.

        Never fatal. The enquiry is already saved, and losing a lead because a
        slot could not be recorded would be the expensive half of the two.
        """
        try:
            await self._enquiries.add_consultation(
                Consultation(
                    enquiry_id=enquiry.id,
                    scheduled_at=when,
                    status=ConsultationStatus.REQUESTED,
                )
            )
            await self._enquiries.add_event(
                EnquiryEvent(
                    enquiry_id=enquiry.id,
                    kind=EnquiryEventKind.CONSULTATION_REQUESTED,
                    payload={"requested_at": when.isoformat()},
                )
            )
        except Exception:  # noqa: BLE001 — see docstring
            logger.exception(
                "[enquiry] %s saved but its requested slot was not", enquiry.id
            )

    async def _notify(self, enquiry: Enquiry) -> None:
        """Send both messages at once, and never let either fail the request.

        Concurrent rather than sequential: two round trips to a mail provider,
        one after the other, is latency a visitor waits through after they have
        already pressed submit.

        `return_exceptions=True` because the lead is already saved. The adapter
        logs its own failures; this catches anything it does not, so a mail
        provider having a bad afternoon cannot turn a captured lead into a 500
        and a lost customer.
        """
        tasks = [
            self._email.send_enquiry_acknowledgement(
                to=enquiry.email, name=enquiry.full_name, event_type=enquiry.event_type
            ),
            # The office's bell, independent of the mail above. Addressed to
            # every member of staff rather than to one inbox, which is the whole
            # reason it is not a side effect of sending that email.
            self._notifier.enquiry_received(
                enquiry_id=enquiry.id,
                name=enquiry.full_name,
                event_type=enquiry.event_type,
                message=enquiry.message,
            ),
        ]
        if self._notify_email:
            tasks.append(
                self._email.send_enquiry_received(
                    to=self._notify_email,
                    name=enquiry.full_name,
                    email=enquiry.email,
                    phone=enquiry.phone,
                    event_type=enquiry.event_type,
                    event_date=enquiry.event_date,
                    message=enquiry.message,
                    enquiry_id=enquiry.id,
                )
            )
        else:
            # Not "nobody was told" any more: the console's bell is fed
            # above regardless. Still worth a warning, because whoever is away
            # from the console is the person an email would have reached.
            logger.warning(
                "[enquiry] %s saved and shown in the console, but "
                "ENQUIRY_NOTIFICATION_EMAIL is unset so no email went out",
                enquiry.id,
            )

        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, BaseException):
                logger.error(
                    "[enquiry] %s saved; notification failed: %r", enquiry.id, result
                )
