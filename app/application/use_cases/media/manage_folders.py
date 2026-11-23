"""Organising a shoot into named parts.

Filing, and nothing but filing. Every method here leaves `released_at` exactly
where it found it: deciding how the work is arranged and deciding what the
client may see are separate judgements, taken at different moments and often by
different people. A photographer tidying up on a Sunday evening must not
thereby publish the test exposures, and the only way to guarantee that is for
this module never to touch visibility at all.

The destructive path is deliberately not destructive. Deleting a folder unfiles
its contents first and removes a label second — a folder never owns a
photograph, and a tidy-up that could lose a morning's work is not a tidy-up.
"""

from uuid import UUID

from app.core.exceptions import (
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.domain.entities.folder import Folder
from app.domain.entities.user import User
from app.domain.repositories.folder_repository import FolderRepository
from app.domain.repositories.media_repository import MediaRepository
from app.domain.repositories.project_repository import ProjectRepository

#: Enough for the longest day anybody shoots, and low enough that a runaway
#: client cannot turn one project into thousands of rows.
MAX_FOLDERS = 60


class ManageFolders:
    def __init__(
        self,
        folders: FolderRepository,
        media: MediaRepository,
        projects: ProjectRepository,
    ) -> None:
        self._folders = folders
        self._media = media
        self._projects = projects

    async def _project_for(self, project_id: UUID, actor: User):
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        # The same rule that governs releasing and deleting: whoever runs the
        # shoot. A client must never reach this — how the work is arranged is
        # not theirs to change, and folders are staff-side organisation.
        if not project.is_managed_by(actor):
            raise PermissionDeniedError("You cannot manage this project.")
        return project

    async def _require(self, project_id: UUID, folder_id: UUID) -> Folder:
        folder = await self._folders.get_by_id(folder_id)
        # Checked against the project as well as for existence, so a folder id
        # from another project cannot be operated on by someone who merely
        # manages this one.
        if folder is None or folder.project_id != project_id:
            raise EntityNotFoundError("That folder is no longer here.")
        return folder

    async def list_folders(self, *, actor: User, project_id: UUID) -> list[Folder]:
        """The folders, as this person is allowed to see them.

        Readable by anyone who can see the project, unlike every other method
        here: a client browsing their gallery by part of the day is the point
        of folders being client-facing at all. Changing them stays with
        whoever runs the shoot.

        What a client gets is narrower in two ways, and both matter. Counts
        describe only released work, so a folder cannot announce how much is
        being withheld. And a folder with nothing released is left out
        entirely — an empty "Reception" tells a client the reception exists
        and they are not being shown it, which is worse than silence.
        """
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_visible_to(actor):
            raise PermissionDeniedError("You do not have access to this project.")

        if project.is_managed_by(actor):
            return await self._folders.list_for_project(project_id)

        listed = await self._folders.list_for_project(project_id, released_only=True)
        return [folder for folder in listed if folder.asset_count > 0]

    async def create(self, *, actor: User, project_id: UUID, name: str) -> Folder:
        await self._project_for(project_id, actor)
        existing = await self._folders.list_for_project(project_id)
        if len(existing) >= MAX_FOLDERS:
            raise ValidationError(
                f"A project can have {MAX_FOLDERS} folders. Rename or remove one first."
            )
        # Built before the duplicate check so the name is trimmed and clipped
        # the same way it will be stored — otherwise "Ceremony " slips past a
        # comparison against "Ceremony".
        folder = Folder(
            project_id=project_id,
            name=name,
            position=await self._folders.next_position(project_id),
        )
        if await self._folders.find_by_name(project_id, folder.name) is not None:
            raise ValidationError(f"There is already a folder called {folder.name}.")
        return await self._folders.add(folder)

    async def rename(
        self, *, actor: User, project_id: UUID, folder_id: UUID, name: str
    ) -> Folder:
        await self._project_for(project_id, actor)
        folder = await self._require(project_id, folder_id)
        folder.rename(name)
        clash = await self._folders.find_by_name(project_id, folder.name)
        if clash is not None and clash.id != folder.id:
            raise ValidationError(f"There is already a folder called {folder.name}.")
        return await self._folders.update(folder)

    async def reorder(
        self, *, actor: User, project_id: UUID, folder_ids: list[UUID]
    ) -> list[Folder]:
        """Set the running order from a complete list of ids.

        The whole order rather than a move instruction: a drag that sends
        "folder X is now third" has to be reconciled against whatever everyone
        else's positions are, and two people dragging at once leave a sequence
        that means nothing. A full list is the order.
        """
        await self._project_for(project_id, actor)
        known = {f.id: f for f in await self._folders.list_for_project(project_id)}
        if set(folder_ids) != set(known):
            raise ValidationError("That is not the full list of this project's folders.")
        for position, folder_id in enumerate(folder_ids):
            folder = known[folder_id]
            folder.position = position
            await self._folders.update(folder)
        return await self._folders.list_for_project(project_id)

    async def file_assets(
        self,
        *,
        actor: User,
        project_id: UUID,
        asset_ids: list[UUID],
        folder_id: UUID | None,
    ) -> int:
        """Move photographs into a folder, or out of all of them with `None`."""
        await self._project_for(project_id, actor)
        if folder_id is not None:
            await self._require(project_id, folder_id)
        return await self._media.set_folder(project_id, asset_ids, folder_id)

    async def delete(self, *, actor: User, project_id: UUID, folder_id: UUID) -> int:
        """Remove a folder. Returns how many photographs were unfiled.

        Order matters: unfile first, drop the label second. The other way
        round leaves rows pointing at a folder that no longer exists, which is
        a photograph nobody can find by any route.
        """
        await self._project_for(project_id, actor)
        await self._require(project_id, folder_id)
        unfiled = await self._media.unfile_all(folder_id)
        await self._folders.delete(folder_id)
        return unfiled
