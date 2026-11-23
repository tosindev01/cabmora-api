"""An `EmailSender` that honours what the recipient asked not to receive.

A decorator rather than a check inside each use case. Nine call sites send the
three mutable kinds today, across seven files; a preference tested in nine
places is a preference forgotten in the tenth, and the tenth is whichever one
is written next. Here there is exactly one gate, and it sits at the boundary
where mail actually leaves — which is also the only place that is true for the
scheduled reminder job as well as for a request.

Everything not listed in `NotificationKind` passes through untouched, so an
invite, a password reset and "your photographs are ready" cannot be silenced by
any setting.
"""

from app.domain.entities.preferences import NotificationKind
from app.domain.repositories.preferences_repository import PreferencesRepository
from app.domain.services.email_sender import EmailSender


class PreferenceAwareEmailSender(EmailSender):
    def __init__(self, inner: EmailSender, preferences: PreferencesRepository) -> None:
        self._inner = inner
        self._preferences = preferences

    async def _wanted(self, to: str, kind: NotificationKind) -> bool:
        # By address, because that is all the send path knows. An address with
        # no account gets the default, which is "send" — a notice to somebody
        # who is not a user is not something a user preference can mute.
        return (await self._preferences.get_by_email(to)).wants(kind)

    # ── mutable ──────────────────────────────────────────────────────────
    async def send_invoice_issued(self, *, to: str, **kwargs) -> None:
        if await self._wanted(to, NotificationKind.INVOICES):
            await self._inner.send_invoice_issued(to=to, **kwargs)

    async def send_consultation_booked(self, *, to: str, **kwargs) -> None:
        if await self._wanted(to, NotificationKind.BOOKINGS):
            await self._inner.send_consultation_booked(to=to, **kwargs)

    async def send_consultation_reminder(self, *, to: str, **kwargs) -> None:
        if await self._wanted(to, NotificationKind.BOOKINGS):
            await self._inner.send_consultation_reminder(to=to, **kwargs)

    async def send_project_message(self, *, to: str, **kwargs) -> None:
        if await self._wanted(to, NotificationKind.MESSAGES):
            await self._inner.send_project_message(to=to, **kwargs)

    async def send_amendment_resolved(self, *, to: str, **kwargs) -> None:
        if await self._wanted(to, NotificationKind.MESSAGES):
            await self._inner.send_amendment_resolved(to=to, **kwargs)

    # ── never mutable ────────────────────────────────────────────────────
    # Listed one by one rather than caught by a `__getattr__`: a new method on
    # the ABC should fail loudly here and make somebody decide whether it can
    # be declined, instead of silently defaulting either way.
    async def send_invite(self, **kwargs) -> None:
        await self._inner.send_invite(**kwargs)

    async def send_password_reset(self, **kwargs) -> None:
        await self._inner.send_password_reset(**kwargs)

    async def send_creator_application_received(self, **kwargs) -> None:
        await self._inner.send_creator_application_received(**kwargs)

    async def send_creator_approved(self, **kwargs) -> None:
        await self._inner.send_creator_approved(**kwargs)

    async def send_creator_declined(self, **kwargs) -> None:
        await self._inner.send_creator_declined(**kwargs)

    async def send_gallery_ready(self, **kwargs) -> None:
        # The one message the product exists to deliver.
        await self._inner.send_gallery_ready(**kwargs)

    async def send_enquiry_received(self, **kwargs) -> None:
        await self._inner.send_enquiry_received(**kwargs)

    async def send_enquiry_acknowledgement(self, **kwargs) -> None:
        await self._inner.send_enquiry_acknowledgement(**kwargs)
