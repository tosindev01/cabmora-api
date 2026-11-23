from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID


class EmailSender(ABC):
    """Outbound email, as an interface the application depends on.

    Intent-named methods rather than a generic `send(subject, body)`: the use
    case should say *what happened*, not compose copy. Templates and provider
    details live in infrastructure, so switching from the logging
    implementation to Mailtrap changes one class and no use case.
    """

    @abstractmethod
    async def send_invite(self, *, to: str, first_name: str, invite_url: str) -> None:
        """Ask someone to set a password on an account created for them."""

    @abstractmethod
    async def send_password_reset(self, *, to: str, first_name: str, reset_url: str) -> None:
        """Offer someone a one-time link to choose a new password."""

    @abstractmethod
    async def send_creator_application_received(
        self, *, to: str, first_name: str, studio_name: str
    ) -> None:
        """Acknowledge a studio's application to join Flow."""

    @abstractmethod
    async def send_creator_approved(
        self, *, to: str, first_name: str, studio_name: str, setup_url: str
    ) -> None:
        """Tell an approved studio they are in, and how to set a password."""

    @abstractmethod
    async def send_creator_declined(
        self, *, to: str, first_name: str, studio_name: str
    ) -> None:
        """Tell a studio we are not taking them on."""

    @abstractmethod
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
        """Tell a client their photographs are waiting.

        `hands_over_originals` says whether what they are about to open is the
        finished file or a marked proof. The message used to assert the second
        unconditionally — "previews carry our watermark until you accept the
        work" — which is simply untrue on a project set to never watermark,
        and the wrong way round on one set to always.

        `note` is a line from whoever released them — "the beach ones are
        still coming", "we caught the speech". Optional, and defaulted so the
        other senders of this message are unaffected: the point of a personal
        note is that it is personal, and a photographer with nothing to add
        should not be made to invent something.
        """

    @abstractmethod
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
        """Tell one side that the other has written something.

        One method for both directions rather than two. The client is told
        their photographer replied and the studio that their client wrote;
        the only differences are the name, the link and which way round the
        sentence reads, and two near-identical methods would drift.

        `body` is quoted in the message. A notification that only says "you
        have a new message" makes somebody sign in to find out whether it
        needed them, which is how notifications get ignored.
        """

    @abstractmethod
    async def send_amendment_resolved(
        self,
        *,
        to: str,
        first_name: str,
        project_title: str,
        request: str,
        gallery_url: str,
    ) -> None:
        """Tell a client the change they asked for has been made."""

    @abstractmethod
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
        bank: object | None = None,
    ) -> None:
        """Tell a client an invoice is ready, for how much, and by when.

        `bank` is the account a transfer should go to, or None where it has
        not been configured — the message then omits the instructions rather
        than printing an invented one. Typed loosely here on purpose: the
        domain's email port should not have to know the shape of a value
        object that belongs to invoicing.

        `document` is `(filename, bytes, content_type)` — the invoice itself,
        so it can be filed or forwarded without signing in, which is what an
        accountant actually asks for. Optional: a failure to render one must
        not stop the client being told they owe money.
        """

    @abstractmethod
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
        """Tell whoever watches the pipeline that a lead has arrived.

        Carries the whole enquiry rather than a "you have a new lead" nudge: the
        recipient is usually on a phone, and a notification that forces a laptop
        before you know whether it is a wedding or a spam bot gets ignored.
        """

    @abstractmethod
    async def send_enquiry_acknowledgement(
        self, *, to: str, name: str, event_type: str
    ) -> None:
        """Tell the sender we have it, and what happens next.

        Without this a client fills in the form and hears nothing, which reads
        as "they never got it" long before it reads as "they are busy".
        """

    @abstractmethod
    async def send_consultation_booked(
        self,
        *,
        to: str,
        name: str,
        starts_at: datetime,
        duration_minutes: int,
        meeting_url: str | None,
    ) -> None:
        """Confirm a call the moment it is put in the diary.

        Sent immediately, not batched: a client who is told about a call only
        by its thirty-minute reminder has had no chance to say the time does not
        work, which makes the reminder worse than no reminder at all.
        """

    @abstractmethod
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
        """Remind one party that a call is about to start.

        One method for both sides rather than two. The client is reminded of a
        call "with Cabmora" and the admin of one "with Amara Okafor" — the only
        difference is `with_name`, and two near-identical methods would drift.
        """
