"""What a photograph looked like before it was corrected.

A client who asks for a change wants to know the change was made, and the team
wants to see what they sent last time before sending again. Both questions are
answered by rows that already exist — `ConfirmUpload` keeps every superseded
frame — and were, until now, reachable by nobody.

Its own request rather than part of the gallery: a wedding is four hundred
photographs and perhaps three of them were ever corrected, so minting links
for history on every gallery load would pay for something almost nobody opens.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.entities.asset import AssetKind
from app.domain.entities.user import User
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.media_repository import MediaRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.services.media_storage import MediaStorage

from ._history import earlier_versions
from ._links import AssetLinker


@dataclass(frozen=True)
class AssetVersion:
    id: UUID
    filename: str
    #: None when this viewer may not be handed this file. A version with no
    #: link still appears: that a correction happened is not a secret, even
    #: where the file behind it is not theirs.
    url: str | None
    uploaded_at: datetime
    #: True for the frame currently in the gallery, false for what it
    #: replaced. Said explicitly so a comparison cannot draw them the wrong
    #: way round by relying on list order.
    is_current: bool


class ListAssetVersions:
    def __init__(
        self,
        projects: ProjectRepository,
        media: MediaRepository,
        storage: MediaStorage,
        invoices: InvoiceRepository,
    ) -> None:
        self._projects = projects
        self._media = media
        self._links = AssetLinker(media, storage, invoices)

    async def execute(
        self, *, project_id: UUID, asset_id: UUID, actor: User
    ) -> list[AssetVersion]:
        """Newest first, the current frame at the head.

        A client may see an earlier version for the same reason they may see
        the one that replaced it: a correction inherits the release state of
        the frame it corrected, so anything with history here was already
        theirs to look at. Nothing new is disclosed, and the watermark policy
        applies to an old frame exactly as it does to the current one.
        """
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_visible_to(actor):
            raise PermissionDeniedError("You do not have access to this project.")

        everything = await self._media.list_project_assets(project_id)
        originals = {
            asset.id: asset
            for asset in everything
            if asset.kind is AssetKind.ORIGINAL
        }

        current = originals.get(asset_id)
        # Checked against *this* project rather than merely existing: an id
        # from another couple's shoot must not resolve just because the caller
        # can open some project.
        if current is None:
            raise EntityNotFoundError("That photograph is not on this project.")

        manages = project.is_managed_by(actor)
        previews = AssetLinker.previews_by_original(everything)
        settled = await self._links.settled(project)

        versions = []
        for index, frame in enumerate([current, *earlier_versions(current, originals)]):
            link = await self._links.mint(
                project=project,
                manages=manages,
                original=frame,
                preview=previews.get(frame.id),
                settled=settled,
            )
            versions.append(
                AssetVersion(
                    id=frame.id,
                    filename=frame.filename,
                    url=link.url,
                    uploaded_at=frame.created_at,
                    is_current=index == 0,
                )
            )
        return versions
