from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.access_group import AccessGroup
from app.domain.entities.user import Permission
from app.domain.repositories.access_group_repository import AccessGroupRepository
from app.infrastructure.models.access_group import (
    AccessGroupModel,
    AccessGroupPermissionModel,
    UserGroupModel,
)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class SqlAlchemyAccessGroupRepository(AccessGroupRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _hydrate(self, models: list[AccessGroupModel]) -> list[AccessGroup]:
        """Attach each group's permissions and how many people are in it.

        Two queries for the page rather than two per group — the same reason
        a list of projects does not ask about its members thirty times.
        """
        groups = [m.to_entity() for m in models]
        if not groups:
            return groups
        ids = [str(g.id) for g in groups]

        perms: dict[str, set[Permission]] = {}
        for group_id, permission in (
            await self._session.execute(
                select(
                    AccessGroupPermissionModel.group_id,
                    AccessGroupPermissionModel.permission,
                ).where(AccessGroupPermissionModel.group_id.in_(ids))
            )
        ).all():
            try:
                perms.setdefault(group_id, set()).add(Permission(permission))
            except ValueError:
                # A permission dropped from the enum but still in the table.
                # Ignored rather than raised: it grants nothing because
                # nothing reads it, and it must not break the groups screen.
                continue

        counts = dict(
            (
                await self._session.execute(
                    select(UserGroupModel.group_id, func.count())
                    .where(UserGroupModel.group_id.in_(ids))
                    .group_by(UserGroupModel.group_id)
                )
            ).all()
        )

        for group in groups:
            group.permissions = perms.get(str(group.id), set())
            group.member_count = int(counts.get(str(group.id), 0))
            group.created_at = _aware(group.created_at)  # type: ignore[assignment]
        return groups

    async def add(self, group: AccessGroup) -> AccessGroup:
        self._session.add(
            AccessGroupModel(
                id=str(group.id), name=group.name, created_at=group.created_at
            )
        )
        await self._write_permissions(group)
        await self._session.commit()
        return group

    async def get_by_id(self, group_id: UUID) -> AccessGroup | None:
        model = await self._session.get(AccessGroupModel, str(group_id))
        if model is None:
            return None
        return (await self._hydrate([model]))[0]

    async def list_all(self) -> list[AccessGroup]:
        rows = await self._session.scalars(
            select(AccessGroupModel).order_by(AccessGroupModel.name)
        )
        return await self._hydrate(list(rows))

    async def update(self, group: AccessGroup) -> AccessGroup:
        model = await self._session.get(AccessGroupModel, str(group.id))
        if model is None:
            raise EntityNotFoundError("Group not found")
        model.name = group.name
        await self._write_permissions(group)
        await self._session.commit()
        return group

    async def _write_permissions(self, group: AccessGroup) -> None:
        # Cleared and rewritten rather than diffed. The set is tiny and a diff
        # is a third place for "what does this group give" to be computed.
        await self._session.execute(
            delete(AccessGroupPermissionModel).where(
                AccessGroupPermissionModel.group_id == str(group.id)
            )
        )
        for permission in group.permissions:
            self._session.add(
                AccessGroupPermissionModel(
                    group_id=str(group.id), permission=permission.value
                )
            )

    async def delete(self, group_id: UUID) -> None:
        for model in (AccessGroupPermissionModel, UserGroupModel):
            await self._session.execute(
                delete(model).where(model.group_id == str(group_id))
            )
        model = await self._session.get(AccessGroupModel, str(group_id))
        if model is not None:
            await self._session.delete(model)
        await self._session.commit()

    async def set_members(self, group_id: UUID, user_ids: set[UUID]) -> None:
        await self._session.execute(
            delete(UserGroupModel).where(UserGroupModel.group_id == str(group_id))
        )
        for user_id in user_ids:
            self._session.add(
                UserGroupModel(user_id=str(user_id), group_id=str(group_id))
            )
        await self._session.commit()

    async def member_ids(self, group_id: UUID) -> list[UUID]:
        rows = await self._session.scalars(
            select(UserGroupModel.user_id).where(
                UserGroupModel.group_id == str(group_id)
            )
        )
        return [UUID(uid) for uid in rows]

    async def set_groups_for_user(self, user_id: UUID, group_ids: set[UUID]) -> None:
        await self._session.execute(
            delete(UserGroupModel).where(UserGroupModel.user_id == str(user_id))
        )
        for group_id in group_ids:
            self._session.add(
                UserGroupModel(user_id=str(user_id), group_id=str(group_id))
            )
        await self._session.commit()
