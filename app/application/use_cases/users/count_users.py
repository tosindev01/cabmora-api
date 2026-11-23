from dataclasses import dataclass

from app.domain.entities.user import UserRole, UserStatus
from app.domain.repositories.user_repository import UserRepository


@dataclass
class UserCounts:
    total: int
    pending: int
    active: int
    suspended: int
    customers: int
    creators: int
    admins: int


class CountUsers:
    """Headline account numbers for the admin dashboard.

    Counted in the database rather than by listing and measuring in Python —
    `list_all` is paginated, so counting its result would quietly report 50
    once there are more than 50 accounts.
    """

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self) -> UserCounts:
        by_status = await self._users.count_by_status()
        by_role = await self._users.count_by_role()
        return UserCounts(
            total=sum(by_status.values()),
            pending=by_status.get(UserStatus.PENDING, 0),
            active=by_status.get(UserStatus.ACTIVE, 0),
            suspended=by_status.get(UserStatus.SUSPENDED, 0),
            customers=by_role.get(UserRole.CUSTOMER, 0),
            creators=by_role.get(UserRole.CREATOR, 0),
            admins=by_role.get(UserRole.ADMIN, 0),
        )
