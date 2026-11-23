from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.folder import Folder


class FolderRepository(ABC):
    @abstractmethod
    async def add(self, folder: Folder) -> Folder: ...

    @abstractmethod
    async def get_by_id(self, folder_id: UUID) -> Folder | None: ...

    @abstractmethod
    async def list_for_project(
        self, project_id: UUID, released_only: bool = False
    ) -> list[Folder]:
        """Every folder on a project, in running order, each with its count.

        `released_only` counts just the work a client has been shown. Their
        count must never describe what is being withheld from them.
        """

    @abstractmethod
    async def find_by_name(self, project_id: UUID, name: str) -> Folder | None:
        """A folder of this name on this project, ignoring case.

        Names are how people refer to folders out loud, so two differing only
        in capitals are the same folder to everyone except the database.
        """

    @abstractmethod
    async def update(self, folder: Folder) -> Folder: ...

    @abstractmethod
    async def delete(self, folder_id: UUID) -> None:
        """Remove the folder. Its contents are unfiled, never deleted.

        Nothing in here owns a photograph — a folder is a label on one. The
        caller unfiles the assets first; this only removes the label, and the
        separation is what stops a tidy-up from destroying a morning's work.
        """

    @abstractmethod
    async def next_position(self, project_id: UUID) -> int:
        """Where a new folder goes: the end of the running order."""
