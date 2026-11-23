from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.gallery_share import GalleryShare
from app.domain.repositories.gallery_share_repository import GalleryShareRepository
from app.infrastructure.models.gallery_share import (
    GalleryShareAssetModel,
    GalleryShareModel,
)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; everything is stored UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _entity(row: GalleryShareModel) -> GalleryShare:
    share = row.to_entity()
    share.expires_at = _aware(share.expires_at)  # type: ignore[assignment]
    share.revoked_at = _aware(share.revoked_at)
    share.last_viewed_at = _aware(share.last_viewed_at)
    share.created_at = _aware(share.created_at)  # type: ignore[assignment]
    return share


class SqlAlchemyGalleryShareRepository(GalleryShareRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _attach_assets(self, shares: list[GalleryShare]) -> list[GalleryShare]:
        """Fill in `asset_ids` for the selective ones.

        One query for the page rather than one per share, like
        `AccessGroupRepository._hydrate`. Whole-gallery shares are skipped
        entirely — they have no rows, and asking about them would make a
        list of thirty links a query about nothing thirty times.
        """
        selective = [s for s in shares if s.selective]
        if not selective:
            return shares

        chosen: dict[str, set[UUID]] = {}
        for share_id, asset_id in (
            await self._session.execute(
                select(
                    GalleryShareAssetModel.share_id,
                    GalleryShareAssetModel.asset_id,
                ).where(
                    GalleryShareAssetModel.share_id.in_([str(s.id) for s in selective])
                )
            )
        ).all():
            chosen.setdefault(share_id, set()).add(UUID(asset_id))

        for share in selective:
            share.asset_ids = frozenset(chosen.get(str(share.id), ()))
        return shares

    # A deleted photograph leaves its row here, and that is safe rather than
    # overlooked: `covers` is only ever asked about assets the gallery still
    # holds, so an id pointing at nothing matches nothing. Worth sweeping one
    # day for tidiness; it changes no behaviour.

    async def add(self, share: GalleryShare) -> GalleryShare:
        self._session.add(GalleryShareModel.from_entity(share))
        for asset_id in share.asset_ids:
            self._session.add(
                GalleryShareAssetModel(
                    share_id=str(share.id), asset_id=str(asset_id)
                )
            )
        await self._session.commit()
        return share

    async def get_by_token_hash(self, token_hash: str) -> GalleryShare | None:
        row = await self._session.scalar(
            select(GalleryShareModel).where(GalleryShareModel.token_hash == token_hash)
        )
        if row is None:
            return None
        return (await self._attach_assets([_entity(row)]))[0]

    async def get_by_id(self, share_id: UUID) -> GalleryShare | None:
        row = await self._session.get(GalleryShareModel, str(share_id))
        if row is None:
            return None
        return (await self._attach_assets([_entity(row)]))[0]

    async def list_for_project(self, project_id: UUID) -> list[GalleryShare]:
        rows = await self._session.scalars(
            select(GalleryShareModel)
            .where(GalleryShareModel.project_id == str(project_id))
            .order_by(GalleryShareModel.created_at.desc())
        )
        return await self._attach_assets([_entity(row) for row in rows])

    async def update(self, share: GalleryShare) -> GalleryShare:
        row = await self._session.get(GalleryShareModel, str(share.id))
        if row is None:
            raise EntityNotFoundError("Share link not found")
        # Listed explicitly, like every repository here. The token, the
        # project and who created it are not editable by anything — a link
        # that could be pointed at another project after the fact would be a
        # way to read somebody else's photographs.
        row.label = share.label
        row.expires_at = share.expires_at
        row.revoked_at = share.revoked_at
        row.last_viewed_at = share.last_viewed_at
        row.views = share.views
        # `selective` and the chosen ids are not editable either. Widening a
        # link after the fact — one photograph becoming the whole wedding —
        # is precisely the surprise this feature exists to remove. Changing
        # your mind means a new link and revoking the old one, which is what
        # losing a link already requires.
        await self._session.commit()
        return share
