"""Hand one photograph over as a file to keep.

Separate from `ListMyMedia` because the two answer different questions. The
library mints a link per photograph when the page loads, for looking at; this
mints one link, on the click, for saving. That distinction is what fixes the
bug it was written for: a view link lives fifteen minutes, so a gallery left
open over lunch held nothing but expired URLs, and the save reported that the
link had expired. Minting at the moment of the click means a stale link is not
a state this can be in.

It returns a URL rather than the bytes, because media never routes through the
API — see `domain/services/media_storage`. The router answers with a redirect
and the browser fetches from the store directly, so a 40 GB film costs this
process one signature.
"""

from uuid import UUID

from app.application.use_cases.media._links import AssetLinker, client_may_see
from app.core.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.entities.asset import Asset, AssetKind
from app.domain.entities.user import User
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.media_repository import MediaRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.services.media_storage import MediaStorage


class DownloadAsset:
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

    async def execute(self, *, actor: User, asset_id: UUID) -> str:
        asset = await self._media.get_asset(asset_id)
        if asset is None:
            raise EntityNotFoundError("No such file.")

        project = await self._projects.get_by_id(asset.project_id)
        if project is None:
            raise EntityNotFoundError("No such file.")

        manages = project.is_managed_by(actor)
        if not manages and not project.is_visible_to(actor):
            # Not found rather than forbidden: whether a particular id exists
            # is not something somebody with no claim on it should learn.
            raise EntityNotFoundError("No such file.")

        settled = await self._links.settled(project)

        # Asked of the original even when a preview is what gets handed over,
        # because the original is what carries release, supersession and the
        # project's permission. `mint` then decides which file that becomes.
        original = await self._original_behind(asset)
        if not manages:
            if not project.allow_downloads:
                raise PermissionDeniedError(
                    "Downloads are not enabled for this project."
                )
            if not client_may_see(project, original, settled=settled):
                raise EntityNotFoundError("No such file.")

        previews = AssetLinker.previews_by_original(
            await self._media.list_project_assets(project.id)
        )
        link = await self._links.mint(
            project=project,
            manages=manages,
            original=original,
            preview=previews.get(original.id),
            settled=settled,
            as_filename=original.filename,
        )
        if link.url is None:
            raise EntityNotFoundError("That file is not ready to download yet.")
        return link.url

    async def _original_behind(self, asset: Asset) -> Asset:
        """The original an id refers to, given either the original or a preview.

        A gallery hands out whichever id it was listing. Resolving it here
        means neither caller has to know which kind it is holding, and a
        preview's id cannot be used to sidestep the checks that live on the
        original.
        """
        if asset.kind is AssetKind.ORIGINAL:
            return asset
        if asset.derived_from is None:
            raise EntityNotFoundError("No such file.")
        original = await self._media.get_asset(asset.derived_from)
        if original is None:
            raise EntityNotFoundError("No such file.")
        return original
