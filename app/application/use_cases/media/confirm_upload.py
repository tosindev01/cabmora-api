"""Record a file once the bucket actually has it.

The verification here is the whole point. A browser can call this having
uploaded nothing, or having uploaded something a different size to what it
declared, and either would leave the gallery describing a file that cannot be
shown. So the object is checked against the provider before a row is written,
and a mismatch takes the object back out rather than leaving litter behind.
"""

import logging
from uuid import UUID

from app.core.exceptions import (
    StorageUnavailableError,
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.domain.entities.project import ProjectStage
from app.domain.entities.project_event import ProjectEvent, ProjectEventKind
from app.domain.entities.asset import (
    Asset,
    AssetKind,
    StorageEvent,
    StorageEventKind,
    StoredObject,
)
from app.domain.entities.user import User
from app.domain.repositories.media_repository import MediaRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.services.media_storage import MediaStorage

logger = logging.getLogger(__name__)


class ConfirmUpload:
    def __init__(
        self,
        projects: ProjectRepository,
        media: MediaRepository,
        storage: MediaStorage,
    ) -> None:
        self._projects = projects
        self._media = media
        self._storage = storage

    async def execute(
        self,
        *,
        project_id: UUID,
        actor: User,
        content_hash: str,
        filename: str,
        content_type: str,
        byte_size: int,
        upload_id: str,
        etags: list[str],
        replaces: UUID | None = None,
    ) -> Asset:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_managed_by(actor):
            raise PermissionDeniedError("You cannot upload to this project.")

        previous: Asset | None = None
        if replaces is not None:
            previous = await self._media.get_asset(replaces)
            # Checked against *this* project, not just existence: a correction
            # aimed at another couple's shoot would otherwise be accepted and
            # quietly hide one of their photographs.
            if previous is None or previous.project_id != project_id:
                raise EntityNotFoundError(
                    "The photograph being replaced is not on this project."
                )
            if not previous.is_original:
                raise ValidationError(
                    "Only an original can be replaced; renditions are made from it."
                )

        content_hash = content_hash.strip().lower()
        blob = StoredObject(
            content_hash=content_hash, byte_size=byte_size, content_type=content_type
        )

        try:
            await self._storage.complete_upload(
                key=blob.key, upload_id=upload_id, etags=etags
            )
        except Exception as exc:  # noqa: BLE001
            # Everything the next person needs, in one line. Unguarded this
            # reached the catch-all handler and came out as "Something went
            # wrong. Please try again." — a sentence that is true of every
            # failure in the system and therefore tells nobody anything.
            logger.exception(
                "[media] completing %s failed: upload_id=%s parts=%s type=%s bytes=%s",
                blob.key, upload_id, len(etags), content_type, byte_size,
            )
            raise StorageUnavailableError(
                "Storage would not finish this upload. Nothing was saved — "
                "try again, and if it keeps happening the server log has the "
                "reason."
            ) from exc

        stored = await self._storage.exists(key=blob.key)
        if stored != byte_size:
            # The object is wrong or absent. Remove it rather than leave bytes
            # in the bucket that no row will ever account for or clean up.
            await self._storage.delete(key=blob.key)
            logger.error(
                "[media] %s completed at %s bytes, expected %s — object removed",
                blob.key, stored, byte_size,
            )
            raise ValidationError(
                "That upload did not arrive intact. Please try it again."
            )

        asset = Asset(
            project_id=project_id,
            content_hash=content_hash,
            kind=AssetKind.ORIGINAL,
            filename=filename,
            uploaded_by=actor.id,
        )
        if previous is not None:
            # Inherits the old frame's release state, so a client who has
            # already seen the photograph they complained about is not left
            # looking at a gap while somebody remembers to release the fix.
            asset.replaces(previous)
        saved = await self._media.record_asset(
            blob,
            asset,
            StorageEvent(
                # The project's owner carries the storage, not whoever happened
                # to be at the keyboard.
                account_id=project.creator_id or actor.id,
                asset_id=asset.id,
                kind=StorageEventKind.ADDED,
                byte_size=byte_size,
            ),
        )
        if previous is not None:
            logger.info(
                "[media] %s replaces %s on project %s", saved.id, previous.id, project_id
            )
        else:
            logger.info("[media] %s stored for project %s", blob.key, project_id)

        await self._begin_editing(project, actor)
        return saved

    async def _begin_editing(self, project, actor) -> None:
        """A photograph in the system means the shoot happened.

        Moved here rather than left to an admin: a stage somebody has to
        remember to set is a stage that is wrong most of the time, and a
        client watching their project sees "Booked" a week after the wedding.

        Only from the two stages where it means something. A project already
        in review does not go back to editing because a replacement frame was
        uploaded — that is an amendment, and it has its own path.
        """
        if project.stage not in (ProjectStage.BOOKED, ProjectStage.SHOOTING):
            return
        previous = project.stage
        project.stage = ProjectStage.EDITING
        await self._projects.update(
            project,
            ProjectEvent(
                project_id=project.id,
                kind=ProjectEventKind.STAGE_CHANGED,
                actor_id=actor.id,
                payload={"from": previous.value, "to": ProjectStage.EDITING.value,
                         "reason": "first upload"},
            ),
        )
