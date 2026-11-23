"""The photographs on a project, with links that work for a few minutes.

Who sees what is decided in `_links`, shared with the version history behind
this gallery, because the answer differs by person and the rule is easy to get
wrong: whoever manages the project sees the originals — they shot them — while
a client sees the watermarked preview until the work is approved and, where
the project says so, paid for.

Links are minted per request and expire. That is what the PRD's
"non-downloadable" requirement can actually deliver: a URL copied out of a
browser stops working the same afternoon.
"""

from dataclasses import dataclass
from uuid import UUID

from app.core.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.entities.asset import Asset, AssetKind
from app.domain.entities.user import User
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.media_repository import MediaRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.services.media_storage import MediaStorage

from ._history import earlier_versions
from ._links import VIEW_TTL, AssetLinker

__all__ = ["ListProjectAssets", "VisibleAsset", "VIEW_TTL"]


@dataclass
class VisibleAsset:
    asset: Asset
    #: None when this person may not see the file yet — the row still appears,
    #: so a client can see that work exists without being handed it.
    url: str | None
    #: True when the file is the untouched original rather than a preview.
    is_original: bool
    #: What `url` points at, so the gallery knows to draw a player rather than
    #: an image. None when there is no link to draw anything from.
    content_type: str | None = None
    #: Set when a later upload replaced this frame. Only whoever manages the
    #: project is shown these — for the client, a replaced photograph is
    #: simply the old one, and showing both in the grid is how you get "which
    #: of these two nearly identical pictures is the fix?".
    superseded_by: UUID | None = None
    #: How many earlier frames this one replaced. A count rather than the
    #: chain itself: a gallery of four hundred photographs should not mint
    #: links for versions nobody has asked to look at. The chain comes from
    #: `ListAssetVersions` when somebody opens one.
    supersedes_count: int = 0


class ListProjectAssets:
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

    async def execute(self, project_id: UUID, actor: User) -> list[VisibleAsset]:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_visible_to(actor):
            raise PermissionDeniedError("You do not have access to this project.")

        manages = project.is_managed_by(actor)
        everything = await self._media.list_project_assets(project_id)
        originals = [a for a in everything if a.kind is AssetKind.ORIGINAL]
        by_id = {asset.id: asset for asset in originals}

        # Which frames have been corrected, and by what. Built from the rows
        # already loaded rather than a second query.
        replaced_by = {
            asset.supersedes: asset.id
            for asset in everything
            if asset.supersedes is not None
        }
        previews = AssetLinker.previews_by_original(everything)
        # Asked once for the page, not once per photograph.
        settled = await self._links.settled(project)

        visible: list[VisibleAsset] = []
        for original in originals:
            replacement = replaced_by.get(original.id)
            if replacement is not None and not manages:
                # The client sees the corrected frame in its place, not both.
                # The earlier one is still reachable through its history,
                # which is a deliberate act rather than a gallery full of
                # near-duplicates.
                continue

            link = await self._links.mint(
                project=project,
                manages=manages,
                original=original,
                preview=previews.get(original.id),
                settled=settled,
            )
            visible.append(
                VisibleAsset(
                    asset=original,
                    url=link.url,
                    is_original=link.is_original and link.url is not None,
                    content_type=link.content_type,
                    superseded_by=replacement,
                    supersedes_count=len(earlier_versions(original, by_id)),
                )
            )
        return visible
