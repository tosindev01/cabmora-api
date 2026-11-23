from dataclasses import dataclass

from app.domain.entities.user import User, UserRole, UserStatus
from app.domain.repositories.user_repository import UserRepository

DEFAULT_PAGE_SIZE = 30


@dataclass
class UserPage:
    items: list[User]
    #: Total matching the *current filters*, not the grand total. A grand total
    #: here would render "page 1 of 12" while a filter shows three rows.
    total: int
    limit: int
    offset: int


class ListUsers:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(
        self,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        roles: list[UserRole] | None = None,
        status: UserStatus | None = None,
        search: str | None = None,
    ) -> UserPage:
        items = await self._users.list_all(
            limit=limit, offset=offset, roles=roles, status=status, search=search
        )
        total = await self._users.count_all(roles=roles, status=status, search=search)
        return UserPage(items=items, total=total, limit=limit, offset=offset)
