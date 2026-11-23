from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.access_group import AccessGroup


class AccessGroupRepository(ABC):
    @abstractmethod
    async def add(self, group: AccessGroup) -> AccessGroup: ...

    @abstractmethod
    async def get_by_id(self, group_id: UUID) -> AccessGroup | None: ...

    @abstractmethod
    async def list_all(self) -> list[AccessGroup]:
        """Every group, with how many people are in each."""

    @abstractmethod
    async def update(self, group: AccessGroup) -> AccessGroup: ...

    @abstractmethod
    async def delete(self, group_id: UUID) -> None:
        """Remove the group and every membership of it.

        The memberships go too, deliberately: a row pointing at a group that
        no longer exists is a membership that grants nothing while looking
        like it grants something.
        """

    @abstractmethod
    async def set_members(self, group_id: UUID, user_ids: set[UUID]) -> None: ...

    @abstractmethod
    async def member_ids(self, group_id: UUID) -> list[UUID]: ...

    @abstractmethod
    async def set_groups_for_user(self, user_id: UUID, group_ids: set[UUID]) -> None:
        """Replace which groups one person is in. The whole set, not a delta."""
