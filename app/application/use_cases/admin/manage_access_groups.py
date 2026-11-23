"""Creating and changing the named bundles an administrator hands out.

The hazard here is leverage, and it is the point of groups rather than a flaw
in them: editing one changes what nine people can reach, in one click, with no
per-person confirmation to slow anybody down. So every read carries the member
count, and the destructive paths say what they are about to affect.
"""

from uuid import UUID

from app.core.exceptions import (
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.domain.entities.access_group import AccessGroup
from app.domain.entities.user import Permission, User, UserRole
from app.domain.repositories.access_group_repository import AccessGroupRepository
from app.domain.repositories.user_repository import UserRepository


def _assert_admin(actor: User) -> None:
    if actor.role is not UserRole.ADMIN:
        raise PermissionDeniedError(
            "Only an administrator can change access groups."
        )


class ManageAccessGroups:
    def __init__(
        self, groups: AccessGroupRepository, users: UserRepository
    ) -> None:
        self._groups = groups
        self._users = users

    async def list_groups(self, *, actor: User) -> list[AccessGroup]:
        _assert_admin(actor)
        return await self._groups.list_all()

    async def create(
        self, *, actor: User, name: str, permissions: set[Permission]
    ) -> AccessGroup:
        _assert_admin(actor)
        # The entity refuses anything outside GRANTABLE, so a group cannot be
        # the route around the per-user rules.
        return await self._groups.add(AccessGroup(name=name, permissions=permissions))

    async def update(
        self,
        *,
        actor: User,
        group_id: UUID,
        name: str | None = None,
        permissions: set[Permission] | None = None,
    ) -> AccessGroup:
        _assert_admin(actor)
        group = await self._require(group_id)
        if name is not None:
            group.rename(name)
        if permissions is not None:
            group.set_permissions(permissions)
        return await self._groups.update(group)

    async def delete(self, *, actor: User, group_id: UUID) -> None:
        _assert_admin(actor)
        await self._require(group_id)
        # Memberships go with it. A row pointing at a group that no longer
        # exists is a membership that grants nothing while looking like it
        # grants something.
        await self._groups.delete(group_id)

    async def set_members(
        self, *, actor: User, group_id: UUID, user_ids: set[UUID]
    ) -> AccessGroup:
        """Who is in this group. The whole set, not a delta."""
        _assert_admin(actor)
        await self._require(group_id)
        people = await self._users.get_many(user_ids)
        # Same rule as a direct grant: these permissions mean nothing outside
        # the console, and an administrator needs none of them.
        wrong = [
            u.full_name
            for u in people.values()
            if u.role is not UserRole.COORDINATOR
        ]
        if wrong:
            raise ValidationError(
                "Only coordinators can be put in an access group: "
                + ", ".join(sorted(wrong))
            )
        if actor.id in user_ids:
            raise PermissionDeniedError("You cannot put yourself in a group.")
        await self._groups.set_members(group_id, user_ids)
        return await self._require(group_id)

    async def members(self, *, actor: User, group_id: UUID) -> list[UUID]:
        _assert_admin(actor)
        await self._require(group_id)
        return await self._groups.member_ids(group_id)

    async def set_groups_for_user(
        self, *, actor: User, user_id: UUID, group_ids: set[UUID]
    ) -> User:
        """Which groups one person is in — the same change from the other end."""
        _assert_admin(actor)
        if actor.id == user_id:
            raise PermissionDeniedError("You cannot change your own access.")
        target = await self._users.get_by_id(user_id)
        if target is None:
            raise EntityNotFoundError("User not found")
        if target.role is not UserRole.COORDINATOR:
            raise ValidationError(
                "Only a coordinator can be put in an access group."
            )
        for group_id in group_ids:
            await self._require(group_id)
        await self._groups.set_groups_for_user(user_id, group_ids)
        refreshed = await self._users.get_by_id(user_id)
        assert refreshed is not None
        return refreshed

    async def _require(self, group_id: UUID) -> AccessGroup:
        group = await self._groups.get_by_id(group_id)
        if group is None:
            raise EntityNotFoundError("Group not found")
        return group
