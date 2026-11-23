from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.asset import AssetKind
from app.domain.entities.folder import Folder
from app.domain.repositories.folder_repository import FolderRepository
from app.infrastructure.models.asset import AssetModel
from app.infrastructure.models.folder import FolderModel


class SqlAlchemyFolderRepository(FolderRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _counts(self, project_id: UUID, released_only: bool = False) -> dict[str, int]:
        """How many photographs are filed in each folder of one project.

        Counts what the gallery actually shows, which is originals that have
        not been superseded — a folder claiming twelve beside a grid of eleven
        is the kind of small untruth that stops people trusting the number at
        all.

        `NOT EXISTS` rather than an outer join to the replacements: a join
        multiplies rows when a frame has been corrected more than once, and
        the count silently inflates.
        """
        newer = aliased(AssetModel)
        replaced = (
            select(newer.id)
            .where(newer.supersedes == AssetModel.id)
            .exists()
        )
        query = select(AssetModel.folder_id, func.count()).where(
            AssetModel.project_id == str(project_id),
            AssetModel.kind == AssetKind.ORIGINAL.value,
            AssetModel.folder_id.is_not(None),
            ~replaced,
        )
        if released_only:
            # A client's count must only ever describe work they have been
            # shown. Counting the rest would say "Ceremony 40" over a folder
            # holding four released frames, which tells them exactly how much
            # is being withheld — and the withholding is deliberate.
            query = query.where(AssetModel.released_at.is_not(None))
        rows = await self._session.execute(query.group_by(AssetModel.folder_id))
        return {folder_id: total for folder_id, total in rows.all()}

    async def add(self, folder: Folder) -> Folder:
        self._session.add(
            FolderModel(
                id=str(folder.id),
                project_id=str(folder.project_id),
                name=folder.name,
                position=folder.position,
                created_at=folder.created_at,
            )
        )
        await self._session.commit()
        return folder

    async def get_by_id(self, folder_id: UUID) -> Folder | None:
        row = await self._session.get(FolderModel, str(folder_id))
        return row.to_entity() if row else None

    async def list_for_project(
        self, project_id: UUID, released_only: bool = False
    ) -> list[Folder]:
        rows = await self._session.scalars(
            select(FolderModel)
            .where(FolderModel.project_id == str(project_id))
            # Position first, then creation — two folders made in one sitting
            # share a position until somebody orders them, and without the
            # tiebreak they would swap places between page loads.
            .order_by(FolderModel.position, FolderModel.created_at)
        )
        folders = [row.to_entity() for row in rows]
        counts = await self._counts(project_id, released_only=released_only)
        for folder in folders:
            folder.asset_count = counts.get(str(folder.id), 0)
        return folders

    async def find_by_name(self, project_id: UUID, name: str) -> Folder | None:
        row = await self._session.scalars(
            select(FolderModel).where(
                FolderModel.project_id == str(project_id),
                func.lower(FolderModel.name) == name.strip().lower(),
            )
        )
        found = row.first()
        return found.to_entity() if found else None

    async def update(self, folder: Folder) -> Folder:
        row = await self._session.get(FolderModel, str(folder.id))
        if row is None:
            raise EntityNotFoundError("Folder not found")
        row.name = folder.name
        row.position = folder.position
        await self._session.commit()
        return folder

    async def delete(self, folder_id: UUID) -> None:
        await self._session.execute(
            delete(FolderModel).where(FolderModel.id == str(folder_id))
        )
        await self._session.commit()

    async def next_position(self, project_id: UUID) -> int:
        highest = await self._session.scalar(
            select(func.max(FolderModel.position)).where(
                FolderModel.project_id == str(project_id)
            )
        )
        return (highest + 1) if highest is not None else 0
