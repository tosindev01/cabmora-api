from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.rating import Rating, ReviewStatus
from app.domain.repositories.rating_repository import RatingRepository
from app.infrastructure.models.rating import RatingModel


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; everything is stored UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _entity(row: RatingModel) -> Rating:
    rating = row.to_entity()
    rating.created_at = _aware(rating.created_at)  # type: ignore[assignment]
    rating.updated_at = _aware(rating.updated_at)
    return rating


class SqlAlchemyRatingRepository(RatingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, rating: Rating) -> Rating:
        self._session.add(RatingModel.from_entity(rating))
        await self._session.commit()
        return rating

    async def get_for_project(self, project_id: UUID) -> Rating | None:
        row = await self._session.scalar(
            select(RatingModel).where(RatingModel.project_id == str(project_id))
        )
        return _entity(row) if row else None

    async def get_by_id(self, rating_id: UUID) -> Rating | None:
        row = await self._session.get(RatingModel, str(rating_id))
        return _entity(row) if row else None

    async def delete(self, rating_id: UUID) -> None:
        row = await self._session.get(RatingModel, str(rating_id))
        if row is not None:
            await self._session.delete(row)
            await self._session.commit()

    async def list_all(
        self,
        *,
        status: ReviewStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Rating]:
        stmt = select(RatingModel)
        if status is not None:
            stmt = stmt.where(RatingModel.status == status.value)
        rows = await self._session.scalars(
            stmt.order_by(RatingModel.created_at.desc()).limit(limit).offset(offset)
        )
        return [_entity(row) for row in rows]

    async def count_all(self, *, status: ReviewStatus | None = None) -> int:
        stmt = select(func.count()).select_from(RatingModel)
        if status is not None:
            stmt = stmt.where(RatingModel.status == status.value)
        return int(await self._session.scalar(stmt) or 0)

    async def list_published(self, limit: int = 12) -> list[Rating]:
        # Both conditions, not just the status. The consent flag is the one
        # that must never be skipped, and this is the query an endpoint with
        # no session behind it runs.
        rows = await self._session.scalars(
            select(RatingModel)
            .where(
                RatingModel.status == ReviewStatus.PUBLISHED.value,
                RatingModel.may_publish.is_(True),
                RatingModel.words != "",
            )
            .order_by(RatingModel.created_at.desc())
            .limit(limit)
        )
        return [_entity(row) for row in rows]

    async def update(self, rating: Rating) -> Rating:
        row = await self._session.get(RatingModel, str(rating.id))
        if row is None:
            raise EntityNotFoundError("Rating not found")
        # Listed explicitly, like every repository here. The project and the
        # person who left it are not editable by anything.
        row.stars = rating.stars
        row.words = rating.words
        row.may_publish = rating.may_publish
        row.status = rating.status.value
        row.moderated_by = str(rating.moderated_by) if rating.moderated_by else None
        row.moderated_at = rating.moderated_at
        row.updated_at = rating.updated_at
        await self._session.commit()
        return rating
