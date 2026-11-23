from uuid import UUID

from app.core.exceptions import EntityNotFoundError, ValidationError
from app.domain.entities.user import User, UserRole, UserStatus
from app.domain.repositories.user_repository import UserRepository


class UpdateUser:
    """Administrative changes to an account: its role, and whether it is active.

    Deliberately in `use_cases/users/` rather than `use_cases/admin/` — this
    does not know who is allowed to call it. The router enforces that with
    `CurrentAdminDep`, the same way `ListEnquiries` is a plain use case behind
    a guarded route.
    """

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(
        self,
        user_id: UUID,
        actor_id: UUID,
        role: UserRole | None = None,
        status: UserStatus | None = None,
    ) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise EntityNotFoundError("User not found")

        # No endpoint anywhere grants UserRole.ADMIN to a fresh account, so an
        # admin who demotes or suspends themselves may have no way back without
        # direct database access. Refusing the self-inflicted case costs nothing
        # and removes the only realistic lockout.
        if user_id == actor_id:
            if role is not None and role != UserRole.ADMIN:
                raise ValidationError("You cannot remove your own admin role.")
            if status is not None and status is not UserStatus.ACTIVE:
                raise ValidationError("You cannot suspend your own account.")

        if role is not None:
            user.role = role
        if status is not None:
            user.status = status
        return await self._users.update(user)
