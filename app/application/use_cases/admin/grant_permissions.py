"""Changing what one coordinator may reach.

Additive by construction: a grant adds to the role's baseline and can never
subtract from it, so "why can Devon not see Projects" is never a puzzle about
two rules arguing.
"""

from uuid import UUID

from app.core.exceptions import (
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.domain.entities.user import GRANTABLE, Permission, User, UserRole
from app.domain.repositories.user_repository import UserRepository


class GrantPermissions:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(
        self, *, actor: User, user_id: UUID, permissions: set[Permission]
    ) -> User:
        """Replace this person's grants.

        Refused on four counts, each of which is an escalation if missed.
        """
        if actor.role is not UserRole.ADMIN:
            raise PermissionDeniedError(
                "Only an administrator can change what somebody can reach."
            )
        # Nobody edits their own access. Without this the mechanism is a
        # ladder out of itself for whoever already has one foot on it.
        if actor.id == user_id:
            raise PermissionDeniedError("You cannot change your own access.")

        target = await self._users.get_by_id(user_id)
        if target is None:
            raise EntityNotFoundError("User not found")
        # Console permissions mean nothing to a customer or a creator, and a
        # row that looks like access but grants none is worse than a refusal.
        if target.role is not UserRole.COORDINATOR:
            raise ValidationError(
                "Only a coordinator can be given extra sections. "
                "Administrators already reach everything, and clients and "
                "partners do not use the console."
            )

        # Checked here and not only in the console: a list the interface
        # declines to draw is a list somebody can still POST.
        forbidden = permissions - GRANTABLE
        if forbidden:
            raise ValidationError(
                "These sections cannot be granted: "
                + ", ".join(sorted(p.value for p in forbidden))
            )

        await self._users.set_permissions(user_id, permissions, granted_by=actor.id)
        target.granted = permissions
        return target
