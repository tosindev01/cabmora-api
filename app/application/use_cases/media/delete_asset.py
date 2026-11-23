"""Removing a photograph, and getting the space back.

Storage is the running cost of this product, so a delete that only hides a row
is a delete that keeps charging for the file. This one goes all the way down:
the asset row, the renditions made from it, the reference count on the blob,
and — when nothing points at the bytes any more — the object in the bucket.

Three things make that harder than it looks, and all three are in the model
already rather than invented here:

· **Bytes are shared.** Two projects that upload the same file get one object
  with a reference count of two. Deleting one project's copy must decrement,
  never delete, or the other project's gallery goes blank. The bucket is only
  touched at zero.
· **A photograph is more than one asset.** The original has a watermarked
  preview derived from it, and possibly a chain of earlier versions it
  replaced. Removing the original and leaving its renditions behind would keep
  paying for files nothing can reach.
· **Usage history outlives the asset.** Every removal appends a `REMOVED`
  event. A creator's usage on any past date is a sum over those rows, so
  deleting the row without logging the release would quietly rewrite history.
"""

import logging
from uuid import UUID

from app.core.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.entities.asset import Asset, StorageEvent, StorageEventKind
from app.domain.entities.user import User
from app.domain.repositories.media_repository import MediaRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.services.media_storage import MediaStorage

logger = logging.getLogger(__name__)


class DeleteAsset:
    def __init__(
        self,
        projects: ProjectRepository,
        media: MediaRepository,
        storage: MediaStorage,
    ) -> None:
        self._projects = projects
        self._media = media
        self._storage = storage

    async def execute(self, *, asset_id: UUID, actor: User) -> int:
        """Delete a photograph and everything derived from it.

        Returns how many assets were removed, so the console can say "3 files"
        rather than claiming it removed one thing when a preview and an
        earlier version went with it.
        """
        asset = await self._media.get_asset(asset_id)
        if asset is None:
            raise EntityNotFoundError("That photograph is no longer here.")

        project = await self._projects.get_by_id(asset.project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        # The same rule that governs releasing: whoever runs the shoot. A
        # client must never reach this — deleting the work they are reviewing
        # is not a client's decision.
        if not project.is_managed_by(actor):
            raise PermissionDeniedError("You cannot manage this project.")

        everything = await self._media.list_project_assets(asset.project_id)
        family = self._family(asset, everything)
        for doomed in family:
            # The same account the upload was charged to. `ConfirmUpload`
            # attributes ADDED to the project's owner, and `usage_bytes` sums
            # ADDED minus REMOVED per account — so releasing against anybody
            # else would leave that owner's usage permanently inflated while
            # crediting bytes to somebody who never stored them.
            await self._release(doomed, account_id=project.creator_id or actor.id)

        return len(family)

    @staticmethod
    def _family(asset: Asset, everything: list[Asset]) -> list[Asset]:
        """The asset and everything that only exists because of it.

        Renditions derived from it, and the versions it superseded — a replaced
        frame is unreachable once the frame that replaced it is gone, so
        leaving it behind means paying to store something nobody can open.
        """
        family = {asset.id: asset}
        frontier = [asset.id]
        while frontier:
            parent = frontier.pop()
            for other in everything:
                if other.id in family:
                    continue
                if other.derived_from == parent or other.supersedes == parent:
                    family[other.id] = other
                    frontier.append(other.id)
        return list(family.values())

    async def _release(self, asset: Asset, *, account_id: UUID) -> None:
        # Looked up before the row goes, because the size lives on the blob
        # rather than the asset. Logging a release of zero bytes would leave
        # the account's usage showing a file it no longer holds — the log is
        # the only record, so a wrong number in it cannot be recomputed later.
        blob_before = await self._media.get_object(asset.content_hash)
        released_bytes = blob_before.byte_size if blob_before else 0

        blob = await self._media.remove_asset(
            asset,
            StorageEvent(
                account_id=account_id,
                asset_id=asset.id,
                kind=StorageEventKind.REMOVED,
                # Positive, like ADDED. `usage_bytes` negates by kind rather
                # than by sign — a negative here would add the bytes back.
                byte_size=released_bytes,
            ),
        )
        # Nothing points at these bytes any more, so stop paying for them.
        if blob is not None and blob.reference_count <= 0:
            try:
                await self._storage.delete(key=blob.key)
            except Exception:  # noqa: BLE001
                # The row is already gone and the count already decremented, so
                # the user's delete succeeded. An object left in the bucket is
                # a bill, not a bug the client can see — logged for a sweep
                # rather than raised in their face.
                logger.exception(
                    "[media] %s released but %s was not deleted from the bucket",
                    asset.id, blob.key,
                )
