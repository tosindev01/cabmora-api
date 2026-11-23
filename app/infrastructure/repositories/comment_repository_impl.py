from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.comment import Comment, CommentKind
from app.domain.repositories.comment_repository import CommentRepository
from app.infrastructure.models.comment import CommentModel


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; everything is stored UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _entity(row: CommentModel) -> Comment:
    comment = row.to_entity()
    comment.created_at = _aware(comment.created_at)
    comment.resolved_at = _aware(comment.resolved_at)
    return comment


class SqlAlchemyCommentRepository(CommentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, comment: Comment) -> Comment:
        self._session.add(
            CommentModel(
                id=str(comment.id),
                project_id=str(comment.project_id),
                asset_id=str(comment.asset_id) if comment.asset_id else None,
                parent_id=str(comment.parent_id) if comment.parent_id else None,
                point_x=comment.point_x,
                point_y=comment.point_y,
                author_id=str(comment.author_id),
                body=comment.body,
                kind=comment.kind.value,
                resolved_at=comment.resolved_at,
                resolved_by=str(comment.resolved_by) if comment.resolved_by else None,
                created_at=comment.created_at,
            )
        )
        await self._session.commit()
        return comment

    async def get_by_id(self, comment_id: UUID) -> Comment | None:
        row = await self._session.get(CommentModel, str(comment_id))
        return _entity(row) if row else None

    async def update(self, comment: Comment) -> Comment:
        row = await self._session.get(CommentModel, str(comment.id))
        if row is None:
            raise EntityNotFoundError("Comment not found")
        row.body = comment.body
        row.resolved_at = comment.resolved_at
        row.resolved_by = str(comment.resolved_by) if comment.resolved_by else None
        await self._session.commit()
        return comment

    async def list_for_project(self, project_id: UUID) -> list[Comment]:
        rows = await self._session.scalars(
            select(CommentModel)
            .where(CommentModel.project_id == str(project_id))
            .order_by(CommentModel.created_at)
        )
        return [_entity(row) for row in rows]

    async def list_for_projects(
        self, project_ids: list[UUID]
    ) -> dict[UUID, list[Comment]]:
        if not project_ids:
            return {}
        rows = await self._session.scalars(
            select(CommentModel)
            .where(CommentModel.project_id.in_([str(i) for i in project_ids]))
            .order_by(CommentModel.created_at)
        )
        threads: dict[UUID, list[Comment]] = {pid: [] for pid in project_ids}
        for row in rows:
            threads[UUID(row.project_id)].append(_entity(row))
        return threads

    async def open_counts_for_projects(self, project_ids: list[UUID]) -> dict[UUID, int]:
        if not project_ids:
            return {}
        rows = await self._session.execute(
            select(CommentModel.project_id, func.count())
            .where(
                CommentModel.project_id.in_([str(i) for i in project_ids]),
                CommentModel.kind == CommentKind.AMENDMENT.value,
                CommentModel.resolved_at.is_(None),
            )
            .group_by(CommentModel.project_id)
        )
        return {UUID(pid): count for pid, count in rows.all()}

    async def count_outstanding(self, project_id: UUID) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(CommentModel)
            .where(
                CommentModel.project_id == str(project_id),
                CommentModel.kind == CommentKind.AMENDMENT.value,
                CommentModel.resolved_at.is_(None),
            )
        )
        return int(total or 0)
