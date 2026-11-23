"""Choose which photographs the client may see.

Withheld is the default and releasing is the deliberate act, because the
opposite would be unforgiving: a shoot contains blinks, test frames and shots
the couple would hate, and "remember to hide those" is a rule that fails on the
one occasion it matters.

`ReleaseMode` decides the granularity of the gesture, not the permission.
Under `ALL_AT_ONCE`, releasing anything releases the set — that is what the
setting promises the client, and honouring it here rather than in the console
means a second client of this API cannot quietly break the promise.
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.core.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.entities.asset import Asset, AssetKind
from app.domain.entities.project_event import ProjectEvent, ProjectEventKind
from app.domain.entities.project import ProjectStage
from app.domain.entities.user import User
from app.domain.entities.invoice import is_settled
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.application.use_cases.notifications.notifier import Notifier
from app.domain.repositories.media_repository import MediaRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.user_repository import UserRepository
from app.domain.services.email_sender import EmailSender

logger = logging.getLogger(__name__)

#: How long after telling a client their gallery is ready we stay quiet about
#: the same project.
#:
#: Releasing is not one gesture in practice — you share the ceremony, notice
#: two more worth sending, then a third. Each of those was its own email, so a
#: half hour of curating arrived as five "your photographs are ready"
#: messages, which reads as a broken system rather than an attentive one. The
#: later photographs are in the same gallery the first email already pointed
#: at, so nothing is withheld by staying quiet: they are there when the client
#: opens the link.
QUIET_AFTER_ANNOUNCING = timedelta(minutes=30)


class ReleaseAssets:
    def __init__(
        self,
        projects: ProjectRepository,
        media: MediaRepository,
        users: UserRepository,
        email: EmailSender,
        notifier: Notifier,
        invoices: InvoiceRepository,
        public_base_url: str,
    ) -> None:
        self._projects = projects
        self._media = media
        self._users = users
        self._email = email
        self._notifier = notifier
        self._invoices = invoices
        self._base_url = public_base_url.rstrip("/")

    async def execute(
        self,
        *,
        project_id: UUID,
        actor: User,
        asset_ids: list[UUID],
        released: bool,
        message: str | None = None,
    ) -> list[Asset]:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_managed_by(actor):
            raise PermissionDeniedError("You cannot release work on this project.")

        # Whitespace is not a message. Normalised here rather than in the
        # template, so "did they write anything?" has one answer.
        note = (message or "").strip() or None

        on_project = {
            asset.id: asset
            for asset in await self._media.list_project_assets(
                project_id, kinds=[AssetKind.ORIGINAL.value]
            )
        }
        missing = [str(i) for i in asset_ids if i not in on_project]
        if missing:
            # Named rather than silently skipped: a console that thinks it
            # released a photograph which was never touched is worse than an
            # error, because nobody looks again.
            raise EntityNotFoundError(
                f"{len(missing)} of those photographs are not on this project."
            )

        # The project decides what a release gesture touches, not this use
        # case — the console asks the same question through `PreviewRelease`
        # before confirming, and one rule means the two cannot disagree.
        targets = [on_project[i] for i in project.release_targets(list(on_project), asset_ids)]

        moment = datetime.now(timezone.utc) if released else None
        changed: list[Asset] = []
        for asset in targets:
            if asset.is_released == released:
                continue  # already where it should be
            asset.released_at = moment
            changed.append(await self._media.update_asset(asset))

        if released and changed:
            await self._send_to_review(project, actor)
            told = await self._announce(project, len(changed), note)
            # Recorded whether or not an email went out. Sharing photographs
            # is a thing that happened to the project, and the timeline said
            # nothing about it at all before this — a client could watch the
            # whole history of their shoot without ever seeing the moment
            # their gallery was handed over.
            await self._projects.record_event(
                ProjectEvent(
                    project_id=project.id,
                    kind=ProjectEventKind.GALLERY_RELEASED,
                    actor_id=actor.id,
                    payload={"count": len(changed), "notified": told},
                )
            )
        return changed

    async def _send_to_review(self, project, actor) -> None:
        """Photographs with the client means the client is reviewing them.

        Set here rather than left to an admin. The alternative was a project
        whose client is already leaving comments while the console still says
        "Editing" — and a stage nobody trusts is one nobody reads.

        Only from Editing. A delivered project that has a frame re-released
        has not gone back into review; that is an amendment, which moves the
        stage on its own path.
        """
        moving_to = project.stage_after_release
        if moving_to is None:
            return
        previous = project.stage
        project.stage = moving_to
        await self._projects.update(
            project,
            ProjectEvent(
                project_id=project.id,
                kind=ProjectEventKind.STAGE_CHANGED,
                actor_id=actor.id,
                payload={
                    "from": previous.value,
                    "to": moving_to.value,
                    "reason": "photographs released",
                },
            ),
        )

    async def _announce(self, project, count: int, note: str | None) -> bool:
        """Tell the client their photographs are there, unless we just did.

        One message for the whole gesture, not one per photograph — releasing
        a wedding is two hundred rows and would otherwise be two hundred
        emails. Withholding is deliberately silent: "we have taken some of
        your pictures away" is a conversation, not a notification.

        `note` is whatever the person releasing wanted to say — "the beach
        ones are still coming", "we caught the speech". Optional, and the
        template reads the same without it: a photographer with nothing to add
        should not be made to write something.

        A failure here must not undo the release. The photographs are
        genuinely released; the client simply has not been told, which is
        recoverable by a person and is not worth losing the release over.

        Returns whether the client was actually emailed, so the timeline can
        record it either way.
        """
        if project.customer_id is None:
            return False
        if await self._told_recently(project):
            logger.info(
                "[media] released %s more on %s within the quiet window — not emailing again",
                count, project.id,
            )
            return False
        customer = await self._users.get_by_id(project.customer_id)
        if customer is None:
            return False
        await self._notifier.gallery_released(
            customer_id=customer.id,
            project_id=project.id,
            project_title=project.title,
            photo_count=count,
        )
        try:
            await self._email.send_gallery_ready(
                to=customer.email,
                first_name=customer.first_name,
                project_title=project.title,
                photo_count=count,
                gallery_url=f"{self._base_url}/client/projects/{project.id}",
                note=note,
                hands_over_originals=await self._settled(project),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[media] released %s photographs on %s but could not tell %s",
                count, project.id, customer.email,
            )
            return False
        return True

    async def _settled(self, project) -> bool:
        """Whether the watermark is off — which is what the email describes.

        Read rather than assumed: the message tells a client either "these are
        the full-resolution files" or "these carry our watermark", and sending
        the wrong one of those is the kind of mistake they quote back at you.
        """
        billed, paid = (
            await self._invoices.totals_for_projects([project.id])
        ).get(project.id, (0, 0))
        return project.hands_over_originals(
            settled=is_settled(billed_minor=billed, paid_minor=paid)
        )

    async def _told_recently(self, project) -> bool:
        """Whether this client has just been emailed about this gallery.

        Read from the timeline rather than kept as a column on the project:
        the release events are the record of what the client was told, and a
        second place storing "when did we last email them" would be a second
        thing able to disagree with the audit trail.
        """
        cutoff = datetime.now(timezone.utc) - QUIET_AFTER_ANNOUNCING
        for event in reversed(await self._projects.list_events(project.id)):
            if event.kind is not ProjectEventKind.GALLERY_RELEASED:
                continue
            if not event.payload.get("notified"):
                continue
            # SQLite hands back naive datetimes; everything is stored UTC.
            when = event.occurred_at
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return when > cutoff
        return False
