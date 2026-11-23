from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.asset import (
    MAX_RENDITION_ATTEMPTS,
    Asset,
    AssetKind,
    StorageEvent,
    StorageEventKind,
    StoredObject,
)
from app.domain.repositories.media_repository import MediaRepository
from app.infrastructure.models.asset import (
    AssetModel,
    StorageEventModel,
    StoredObjectModel,
)


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; everything is stored UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _hydrated(row: AssetModel) -> Asset:
    """Entity with its datetimes made aware. SQLite returns them naive."""
    asset = row.to_entity()
    asset.created_at = _aware(asset.created_at)
    if asset.renditions_ready_at:
        asset.renditions_ready_at = _aware(asset.renditions_ready_at)
    if asset.released_at:
        asset.released_at = _aware(asset.released_at)
    return asset


class SqlAlchemyMediaRepository(MediaRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _claim(self, candidate: StoredObject) -> StoredObject:
        # SELECT ... FOR UPDATE so two uploads of identical bytes serialise
        # here instead of both inserting. On SQLite the lock is a no-op and the
        # whole transaction is serialised anyway, which has the same effect.
        row = await self._session.scalar(
            select(StoredObjectModel)
            .where(StoredObjectModel.content_hash == candidate.content_hash)
            .with_for_update()
        )
        if row is None:
            row = StoredObjectModel(
                content_hash=candidate.content_hash,
                byte_size=candidate.byte_size,
                content_type=candidate.content_type,
                reference_count=1,
                created_at=candidate.created_at,
            )
            self._session.add(row)
        else:
            row.reference_count += 1
        await self._session.flush()
        entity = row.to_entity()
        entity.created_at = _aware(entity.created_at)
        return entity

    async def get_object(self, content_hash: str) -> StoredObject | None:
        row = await self._session.get(StoredObjectModel, content_hash)
        return row.to_entity() if row else None

    async def record_asset(
        self, blob: StoredObject, asset: Asset, event: StorageEvent
    ) -> Asset:
        await self._claim(blob)
        self._session.add(
            AssetModel(
                id=str(asset.id),
                project_id=str(asset.project_id),
                content_hash=asset.content_hash,
                kind=asset.kind.value,
                filename=asset.filename,
                uploaded_by=str(asset.uploaded_by),
                derived_from=str(asset.derived_from) if asset.derived_from else None,
                supersedes=str(asset.supersedes) if asset.supersedes else None,
                renditions_ready_at=asset.renditions_ready_at,
                released_at=asset.released_at,
                created_at=asset.created_at,
            )
        )
        self._session.add(
            StorageEventModel(
                id=str(event.id),
                account_id=str(event.account_id),
                asset_id=str(event.asset_id),
                kind=event.kind.value,
                byte_size=event.byte_size,
                occurred_at=event.occurred_at,
            )
        )
        # One commit for the whole unit of work, matching how every other
        # repository here behaves — a half-written asset is not a state any
        # caller should be able to observe.
        await self._session.commit()
        return asset

    async def get_asset(self, asset_id: UUID) -> Asset | None:
        row = await self._session.get(AssetModel, str(asset_id))
        if row is None:
            return None
        entity = row.to_entity()
        entity.created_at = _aware(entity.created_at)
        if entity.renditions_ready_at:
            entity.renditions_ready_at = _aware(entity.renditions_ready_at)
        if entity.released_at:
            entity.released_at = _aware(entity.released_at)
        return entity

    async def update_asset(self, asset: Asset) -> Asset:
        row = await self._session.get(AssetModel, str(asset.id))
        if row is None:
            raise EntityNotFoundError("Asset not found")
        row.renditions_ready_at = asset.renditions_ready_at
        row.released_at = asset.released_at
        row.rendition_attempts = asset.rendition_attempts
        row.rendition_error = asset.rendition_error
        # Written here as well as by `set_folder`, so that saving an entity
        # whose folder changed cannot silently drop the change.
        row.folder_id = str(asset.folder_id) if asset.folder_id else None
        await self._session.commit()
        return asset

    async def counts_for_projects(
        self, project_ids: list[UUID]
    ) -> dict[UUID, tuple[int, int]]:
        if not project_ids:
            return {}
        rows = await self._session.execute(
            select(
                AssetModel.project_id,
                func.count(),
                func.count(AssetModel.released_at),
            )
            .where(
                AssetModel.project_id.in_([str(i) for i in project_ids]),
                AssetModel.kind == AssetKind.ORIGINAL.value,
            )
            .group_by(AssetModel.project_id)
        )
        # `count(column)` ignores nulls, so the second figure counts exactly
        # the rows with a release time on them.
        return {UUID(pid): (total, released) for pid, total, released in rows.all()}

    async def list_project_assets(
        self, project_id: UUID, kinds: list[str] | None = None
    ) -> list[Asset]:
        query = select(AssetModel).where(AssetModel.project_id == str(project_id))
        if kinds:
            query = query.where(AssetModel.kind.in_(kinds))
        rows = await self._session.scalars(query.order_by(AssetModel.created_at))
        return [row.to_entity() for row in rows]

    async def set_folder(
        self, project_id: UUID, asset_ids: list[UUID], folder_id: UUID | None
    ) -> int:
        if not asset_ids:
            return 0
        result = await self._session.execute(
            update(AssetModel)
            .where(
                AssetModel.project_id == str(project_id),
                AssetModel.id.in_([str(i) for i in asset_ids]),
            )
            .values(folder_id=str(folder_id) if folder_id else None)
        )
        await self._session.commit()
        return result.rowcount or 0

    async def unfile_all(self, folder_id: UUID) -> int:
        result = await self._session.execute(
            update(AssetModel)
            .where(AssetModel.folder_id == str(folder_id))
            .values(folder_id=None)
        )
        await self._session.commit()
        return result.rowcount or 0

    async def remove_asset(self, asset: Asset, event: StorageEvent) -> StoredObject | None:
        row = await self._session.get(AssetModel, str(asset.id))
        if row is None:
            raise EntityNotFoundError("Asset not found")
        await self._session.delete(row)

        # The release event is written even though the asset row is going. That
        # is the point of an append-only log: usage history has to survive the
        # thing it describes.
        self._session.add(
            StorageEventModel(
                id=str(event.id),
                account_id=str(event.account_id),
                asset_id=str(event.asset_id),
                kind=event.kind.value,
                byte_size=event.byte_size,
                occurred_at=event.occurred_at,
            )
        )

        blob = await self._session.scalar(
            select(StoredObjectModel)
            .where(StoredObjectModel.content_hash == asset.content_hash)
            .with_for_update()
        )
        if blob is None:
            await self._session.commit()
            return None
        blob.reference_count = max(0, blob.reference_count - 1)
        released = blob.to_entity()
        await self._session.commit()
        return released

    async def list_awaiting_renditions(self, limit: int = 20) -> list[Asset]:
        rows = await self._session.scalars(
            select(AssetModel)
            .where(
                AssetModel.kind == AssetKind.ORIGINAL.value,
                AssetModel.renditions_ready_at.is_(None),
                # A file that has failed this often will fail again. Left in,
                # it is retried every few minutes forever — one corrupt
                # upload becoming a permanent alarm.
                AssetModel.rendition_attempts < MAX_RENDITION_ATTEMPTS,
            )
            # Oldest first: a client waiting since this morning should not be
            # overtaken by an upload from a minute ago.
            .order_by(AssetModel.created_at)
            .limit(limit)
        )
        return [_hydrated(row) for row in rows]

    async def usage_bytes(self, account_id: UUID) -> int:
        """Summed from the log. There is deliberately no counter to drift."""
        total = await self._session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                StorageEventModel.kind == StorageEventKind.ADDED.value,
                                StorageEventModel.byte_size,
                            ),
                            else_=-StorageEventModel.byte_size,
                        )
                    ),
                    0,
                )
            ).where(StorageEventModel.account_id == str(account_id))
        )
        return int(total or 0)
