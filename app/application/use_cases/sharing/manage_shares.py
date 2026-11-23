"""Handing out, listing and taking back links to a gallery.

Who may do it is the point. A client may share their own project — they
commissioned the work and the photographs are of them — but only where an
admin has turned sharing on for that project, because a link that needs no
account exposes photographs of people who agreed to nothing. An admin may
always share, and may always revoke anything a client handed out.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.core.exceptions import (
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.domain.entities.asset import AssetKind
from app.domain.entities.gallery_share import GalleryShare
from app.domain.entities.invoice import is_settled
from app.domain.entities.user import User
from app.domain.repositories.gallery_share_repository import GalleryShareRepository
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.media_repository import MediaRepository
from app.domain.repositories.project_repository import ProjectRepository

from ..media._links import client_may_see


def _may_share(project, actor: User) -> bool:
    """Managers always; the client only where it has been allowed."""
    if project.is_managed_by(actor):
        return True
    return (
        project.customer_id is not None
        and project.customer_id == actor.id
        and project.allow_client_sharing
    )


@dataclass(frozen=True)
class IssuedShare:
    """The record, plus the secret — returned once and never again."""

    share: GalleryShare
    token: str


class ManageGalleryShares:
    def __init__(
        self,
        projects: ProjectRepository,
        shares: GalleryShareRepository,
        media: MediaRepository,
        invoices: InvoiceRepository,
    ) -> None:
        self._projects = projects
        self._shares = shares
        self._media = media
        self._invoices = invoices

    async def _project_for(self, project_id: UUID, actor: User):
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_visible_to(actor):
            raise PermissionDeniedError("You do not have access to this project.")
        return project

    async def create(
        self,
        *,
        project_id: UUID,
        actor: User,
        label: str = "",
        asset_ids: Sequence[UUID] | None = None,
    ) -> IssuedShare:
        project = await self._project_for(project_id, actor)
        if not _may_share(project, actor):
            # Said plainly rather than as a bare 403: the client has not done
            # anything wrong, and "ask us to turn it on" is the actual answer.
            raise PermissionDeniedError(
                "Sharing is switched off for this project. Ask us to turn it on."
            )
        # No check on the stage. There was one, refusing drafts, and it was
        # a second gate on a door somebody had deliberately opened: sharing
        # is already an explicit per-project decision by staff, and drafts
        # are visible to clients anyway — made so because a client who had
        # agreed to a project otherwise could not see it. The same reasoning
        # covers letting them pass it on. Nothing escapes that the client
        # could not already show somebody over their shoulder, and the
        # watermark policy still decides what a recipient is handed.
        chosen = (
            None
            if asset_ids is None
            else await self._confirm_they_are_shareable(project, asset_ids)
        )
        try:
            share, token = GalleryShare.issue(
                project_id=project_id,
                created_by=actor.id,
                label=label,
                asset_ids=chosen,
            )
        except ValueError as exc:
            # The entity refuses an empty selection, because "none" and "all"
            # differ by the entire gallery there. Translated rather than
            # allowed to escape as a 500.
            raise ValidationError(str(exc)) from exc
        return IssuedShare(await self._shares.add(share), token)

    async def _confirm_they_are_shareable(
        self, project, asset_ids: Sequence[UUID]
    ) -> list[UUID]:
        """Narrow the chosen ids to frames that may really be passed on.

        Checked here and not merely in the picker. The picker only offers
        what the client can see, but the ids arrive over HTTP: without this,
        somebody could name an unreleased frame — a blink, a test shot, a
        photograph being withheld — and mint a public link to it. The
        selection decides *which* of the photographs they are already allowed
        to show, never whether they are allowed to show it.

        Deduplicated, and order is not kept: the gallery decides the order it
        shows things in, and it is the same order for everybody.
        """
        wanted = set(asset_ids)
        if not wanted:
            # Left to the entity to refuse, so there is one rule rather than
            # two that could disagree.
            return []

        everything = await self._media.list_project_assets(project.id)
        settled = await self._invoices_settled(project)
        superseded = {a.supersedes for a in everything if a.supersedes is not None}

        allowed = {
            asset.id
            for asset in everything
            if asset.kind is AssetKind.ORIGINAL
            and asset.id not in superseded
            and client_may_see(project, asset, settled=settled)
        }

        unknown = wanted - allowed
        if unknown:
            # Counted rather than listed. An id is not something the person
            # at the keyboard chose or can read, and echoing them back tells
            # whoever sent them which ones exist.
            raise ValidationError(
                f"{len(unknown)} of those photographs cannot be shared yet."
                if len(unknown) > 1
                else "One of those photographs cannot be shared yet."
            )
        return sorted(wanted)

    async def _invoices_settled(self, project) -> bool:
        totals = await self._invoices.totals_for_projects([project.id])
        billed, paid = totals.get(project.id, (0, 0))
        return is_settled(billed_minor=billed, paid_minor=paid)

    async def list_for_project(
        self, *, project_id: UUID, actor: User
    ) -> list[GalleryShare]:
        await self._project_for(project_id, actor)
        return await self._shares.list_for_project(project_id)

    async def revoke(self, *, share_id: UUID, actor: User) -> GalleryShare:
        share = await self._shares.get_by_id(share_id)
        if share is None:
            raise EntityNotFoundError("Share link not found")
        project = await self._project_for(share.project_id, actor)
        # Revoking is deliberately looser than creating: a client whose
        # sharing has since been switched off must still be able to take back
        # a link they handed out, and an admin must be able to kill any of
        # them. Stopping a link is never the dangerous direction.
        if not (project.is_managed_by(actor) or project.customer_id == actor.id):
            raise PermissionDeniedError("You cannot revoke this link.")
        share.revoke()
        return await self._shares.update(share)
