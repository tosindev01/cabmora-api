"""Announcing an event to the people it concerns.

Not a port. Nothing external implements this — it writes our own rows through
repositories the application already owns — so an ABC here would be a seam with
one side. `EmailSender` is an interface because email leaves the building;
this does not.

Not a decorator on `EmailSender` either, which was the tempting shortcut: the
same eleven events already have send sites, and wrapping them would have cost
nothing at the call sites. Two things make it wrong. The sender knows an
**address**, and a notice has to belong to an **account** — for staff mail that
address is one configured inbox (`ENQUIRY_NOTIFICATION_EMAIL`), possibly shared,
so "show every admin the enquiry" cannot be expressed through it at all. And the
preference gate sits on that same chain: a client who turns off invoice *email*
would have silenced their own bell, which is not what that switch says.

So: audiences are resolved here, and a notice is never the echo of an email.

**Announcing must not be able to fail the thing it announces.** Every method
swallows and logs. A lead that is captured, saved and acknowledged must not turn
into a 500 because a notification row would not insert.
"""

import logging
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.domain.entities.notification import Notification, NotificationTopic
from app.domain.entities.user import User, UserRole, UserStatus
from app.domain.repositories.notification_repository import NotificationRepository
from app.domain.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

#: Who counts as "the office" for a notice with no single addressee. Both roles,
#: because a coordinator triaging the pipeline is exactly who a new enquiry is
#: for — telling only admins would make the feature useless to the people doing
#: the work.
STAFF_ROLES = [UserRole.ADMIN, UserRole.COORDINATOR]

#: A ceiling on a fan-out. Far above any plausible Cabmora team and low enough
#: that a bug cannot turn one enquiry into a hundred thousand rows.
MAX_AUDIENCE = 200


def _quote(text: str, *, limit: int = 180) -> str:
    """One line of somebody else's prose, collapsed.

    Newlines are stripped because a feed row is a single line: a message typed
    with hard returns would otherwise render as one long run with the breaks
    silently gone, or blow the row's height apart depending on the CSS.
    """
    flattened = " ".join(text.split())
    if len(flattened) <= limit:
        return flattened
    return flattened[: limit - 1].rstrip() + "…"


class Notifier:
    def __init__(
        self,
        notifications: NotificationRepository,
        users: UserRepository,
    ) -> None:
        self._notifications = notifications
        self._users = users

    # ── delivery ─────────────────────────────────────────────────────────
    async def _deliver(self, rows: Sequence[Notification]) -> None:
        try:
            await self._notifications.add_many(rows[:MAX_AUDIENCE])
        except Exception:  # noqa: BLE001 — see the module docstring
            logger.exception("[notify] %d notice(s) were not recorded", len(rows))

    async def _staff(self) -> list[User]:
        return await self._users.list_all(
            limit=MAX_AUDIENCE, roles=STAFF_ROLES, status=UserStatus.ACTIVE
        )

    async def _tell_staff(
        self,
        *,
        topic: NotificationTopic,
        title: str,
        body: str = "",
        url: str | None = None,
        except_for: UUID | None = None,
    ) -> None:
        """Everyone in the office, optionally minus the person who did it.

        `except_for` because an admin who releases a gallery does not need to be
        told that a gallery was released. Their own action is already on screen,
        and a bell that reports your own clicks back to you is the fastest way
        to teach somebody to ignore it.
        """
        try:
            staff = await self._staff()
        except Exception:  # noqa: BLE001
            logger.exception("[notify] could not work out who to tell about %s", title)
            return
        await self._deliver(
            [
                Notification(
                    user_id=member.id, topic=topic, title=title, body=body, url=url
                )
                for member in staff
                if member.id != except_for
            ]
        )

    async def _tell(
        self,
        user_id: UUID | None,
        *,
        topic: NotificationTopic,
        title: str,
        body: str = "",
        url: str | None = None,
    ) -> None:
        """One person, when there is one.

        `None` is a normal input, not a mistake: a project may have no customer
        assigned yet, and an enquiry comes from somebody who may never have had
        an account. Nothing to do is not an error to log.
        """
        if user_id is None:
            return
        await self._deliver(
            [Notification(user_id=user_id, topic=topic, title=title, body=body, url=url)]
        )

    async def _account_for(self, email: str) -> UUID | None:
        """The account behind an address, or None for a visitor.

        Enquiries and consultations arrive from people who are not users yet.
        They still get the email; the bell has nowhere to put the notice, and
        that is fine.
        """
        try:
            user = await self._users.get_by_email(email)
        except Exception:  # noqa: BLE001
            logger.exception("[notify] could not resolve %s to an account", email)
            return None
        return user.id if user else None

    # ── the pipeline ─────────────────────────────────────────────────────
    async def enquiry_received(
        self,
        *,
        enquiry_id: UUID,
        name: str,
        event_type: str,
        message: str,
    ) -> None:
        """A lead arrived from the public form. The whole office is told."""
        await self._tell_staff(
            topic=NotificationTopic.ENQUIRY,
            title=f"New enquiry from {name}",
            body=_quote(f"{event_type} — {message}" if message else event_type),
            url=f"/admin/enquiries/{enquiry_id}",
        )

    async def consultation_booked(
        self,
        *,
        client_email: str,
        client_name: str,
        starts_at: datetime,
        enquiry_id: UUID | None = None,
    ) -> None:
        """A call went in the diary. Both sides are told."""
        # Built from the parts rather than with `%-d`, which is a libc
        # extension and not portable — the kind of thing that works on a
        # laptop and raises on whatever the container runs.
        when = f"{starts_at.day} {starts_at:%B} at {starts_at:%H:%M}"
        await self._tell(
            await self._account_for(client_email),
            topic=NotificationTopic.BOOKING,
            title="Your consultation is booked",
            body=f"{when}. We will send a reminder before it starts.",
        )
        await self._tell_staff(
            topic=NotificationTopic.BOOKING,
            title=f"{client_name} booked a consultation",
            body=when,
            url=f"/admin/enquiries/{enquiry_id}" if enquiry_id else "/admin/enquiries",
        )

    # ── the work ─────────────────────────────────────────────────────────
    async def project_message(
        self,
        *,
        from_name: str,
        project_id: UUID,
        project_title: str,
        body: str,
        recipient_id: UUID | None = None,
        #: Whether that named person reads this in the console rather than
        #: the customer portal — it decides which app the link points into.
        recipient_is_staff: bool = False,
        to_all_staff: bool = False,
        author_id: UUID | None = None,
        about_a_photograph: bool = False,
    ) -> None:
        """One side wrote something, so the other is told.

        The quoted body is the point. "You have a new message" makes somebody
        sign in to find out whether it needed them, which is how a bell becomes
        a thing people clear without reading.

        Two audiences through one method because the copy is identical and two
        near-identical methods would drift: `recipient_id` for a named person —
        the client, or the creator running the shoot — and `to_all_staff` for a
        project Cabmora runs itself, where there is no one creator to address
        and the office queue is the inbox.
        """
        title = (
            f"{from_name} commented on a photograph in {project_title}"
            if about_a_photograph
            else f"{from_name} wrote on {project_title}"
        )
        if to_all_staff:
            await self._tell_staff(
                topic=NotificationTopic.MESSAGE,
                title=title,
                body=_quote(body),
                url=f"/admin/projects/{project_id}",
                except_for=author_id,
            )
            return
        await self._tell(
            recipient_id,
            topic=NotificationTopic.MESSAGE,
            title=title,
            body=_quote(body),
            url=(
                f"/admin/projects/{project_id}"
                if recipient_is_staff
                else f"/client/projects/{project_id}"
            ),
        )

    async def amendment_resolved(
        self,
        *,
        customer_id: UUID | None,
        project_id: UUID,
        project_title: str,
        request: str,
    ) -> None:
        await self._tell(
            customer_id,
            topic=NotificationTopic.MESSAGE,
            title=f"Your change has been made on {project_title}",
            body=_quote(request),
            url=f"/client/projects/{project_id}",
        )

    async def gallery_released(
        self,
        *,
        customer_id: UUID | None,
        project_id: UUID,
        project_title: str,
        photo_count: int,
    ) -> None:
        pictures = "photograph" if photo_count == 1 else "photographs"
        await self._tell(
            customer_id,
            topic=NotificationTopic.GALLERY,
            title=f"{photo_count} {pictures} are ready on {project_title}",
            body="Have a look and tell us what you think.",
            url=f"/client/projects/{project_id}",
        )

    async def stage_changed(
        self,
        *,
        customer_id: UUID | None,
        project_id: UUID,
        project_title: str,
        stage_label: str,
    ) -> None:
        await self._tell(
            customer_id,
            topic=NotificationTopic.PROJECT,
            title=f"{project_title} moved to {stage_label}",
            url=f"/client/projects/{project_id}",
        )

    async def project_approved(
        self,
        *,
        project_id: UUID,
        project_title: str,
        customer_name: str,
    ) -> None:
        await self._tell_staff(
            topic=NotificationTopic.PROJECT,
            title=f"{customer_name} approved {project_title}",
            body="The work has been signed off.",
            url=f"/admin/projects/{project_id}",
        )

    # ── money ────────────────────────────────────────────────────────────
    async def invoice_issued(
        self,
        *,
        customer_id: UUID | None,
        invoice_id: UUID,
        number: str,
        amount: str,
        project_title: str,
    ) -> None:
        await self._tell(
            customer_id,
            topic=NotificationTopic.INVOICE,
            title=f"Invoice {number} is ready",
            body=f"{amount} for {project_title}.",
            url="/client/billing",
        )

    async def payment_declared(
        self,
        *,
        invoice_id: UUID,
        number: str,
        amount: str,
        payer_name: str,
        actor_id: UUID | None = None,
    ) -> None:
        """Somebody says they have paid, and it needs confirming.

        Deliberately not "payment received": nothing in `RecordPayment` produces
        a confirmed payment, which is what makes it safe to let the person who
        owes the money call it. A bell that said the money had arrived would be
        reporting something nobody has checked.

        `actor_id` is excluded, so an admin entering a bank transfer they just
        reconciled is not told about their own typing — but the rest of the
        office is, which is the point.
        """
        await self._tell_staff(
            topic=NotificationTopic.INVOICE,
            title=f"{payer_name} says they have paid {amount}",
            body=f"Invoice {number} — needs confirming.",
            url=f"/admin/invoices/{invoice_id}",
            except_for=actor_id,
        )

    async def funds_unmatched(
        self, *, funds_id: UUID, amount: str, payer_name: str
    ) -> None:
        """Money arrived that the gateway could not put against an invoice.

        The only notice here that is about something nobody did. Every other
        one follows somebody's action, so somebody already knows; this one is
        the whole mechanism by which anyone finds out at all. Without it the
        money exists solely in the gateway's dashboard, the client believes
        they have paid, and the invoice goes on saying they have not.
        """
        await self._tell_staff(
            topic=NotificationTopic.INVOICE,
            title=f"{amount} arrived with no invoice to put it against",
            body=f"From {payer_name} — needs looking into.",
            url=f"/admin/payments?funds={funds_id}",
        )

    # ── the office ───────────────────────────────────────────────────────
    async def creator_applied(self, *, studio_name: str, contact_name: str) -> None:
        await self._tell_staff(
            topic=NotificationTopic.CREATOR,
            title=f"{studio_name} applied to join Flow",
            body=f"From {contact_name}.",
            url="/admin/creator-applications",
        )

    async def issue_reported(
        self,
        *,
        summary: str,
        reporter_name: str,
        reporter_id: UUID | None = None,
    ) -> None:
        await self._tell_staff(
            topic=NotificationTopic.SUPPORT,
            title=f"{reporter_name} reported a problem",
            body=_quote(summary),
            url="/admin/issues",
            except_for=reporter_id,
        )
