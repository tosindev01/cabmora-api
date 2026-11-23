from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.notification import Notification, NotificationTopic
from app.domain.repositories.notification_repository import NotificationRepository
from app.infrastructure.models.notification import NotificationModel


class SqlAlchemyNotificationRepository(NotificationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_many(self, notifications: Sequence[Notification]) -> None:
        if not notifications:
            # No audience is a normal outcome — a staff fan-out on an install
            # with no coordinators, for instance. Returning early also keeps
            # `add_all([])` + `commit()` off the connection.
            return
        self._session.add_all(
            [NotificationModel.from_entity(each) for each in notifications]
        )
        await self._session.commit()

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        topic: NotificationTopic | None = None,
        unread_only: bool = False,
        limit: int = 30,
        offset: int = 0,
    ) -> list[Notification]:
        query = select(NotificationModel).where(NotificationModel.user_id == str(user_id))
        if topic is not None:
            query = query.where(NotificationModel.topic == topic.value)
        if unread_only:
            query = query.where(NotificationModel.read_at.is_(None))
        query = (
            query.order_by(NotificationModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = await self._session.execute(query)
        return [row.to_entity() for row in rows.scalars().all()]

    async def count_unread(self, user_id: UUID) -> int:
        query = (
            select(func.count())
            .select_from(NotificationModel)
            .where(NotificationModel.user_id == str(user_id))
            .where(NotificationModel.read_at.is_(None))
        )
        return int((await self._session.execute(query)).scalar() or 0)

    async def mark_read(self, user_id: UUID, notification_ids: Sequence[UUID]) -> int:
        if not notification_ids:
            return 0
        statement = (
            update(NotificationModel)
            # Both conditions in one statement. The user_id is what makes an id
            # somebody guessed harmless: it matches no row rather than being
            # caught by a check that could be forgotten.
            .where(NotificationModel.user_id == str(user_id))
            .where(NotificationModel.id.in_([str(each) for each in notification_ids]))
            # Already-read rows are excluded so re-opening the dropdown does
            # not keep moving the stamp forward.
            .where(NotificationModel.read_at.is_(None))
            .values(read_at=datetime.now(timezone.utc))
        )
        result = await self._session.execute(statement)
        await self._session.commit()
        return int(result.rowcount or 0)

    async def mark_all_read(self, user_id: UUID) -> int:
        statement = (
            update(NotificationModel)
            .where(NotificationModel.user_id == str(user_id))
            .where(NotificationModel.read_at.is_(None))
            .values(read_at=datetime.now(timezone.utc))
        )
        result = await self._session.execute(statement)
        await self._session.commit()
        return int(result.rowcount or 0)
