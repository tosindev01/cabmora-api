from uuid import UUID

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository


class GetUser:
    """One account by id.

    Fetched directly rather than picked out of a list so the detail page
    deep-links and survives a refresh — filtering a page that may not contain
    the record would 404 for anyone on page two.
    """

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, user_id: UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise EntityNotFoundError("User not found")
        return user
