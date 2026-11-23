"""Change your own password, having proved you know the current one.

Distinct from the reset flow, which proves identity with a mailed link because
the person cannot sign in. Here they are already signed in, so the proof is the
current password — without it, anyone who walks up to an unlocked laptop owns
the account permanently.
"""

from app.core.exceptions import AuthenticationError, ValidationError
from app.core.security import hash_password, verify_password
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository

#: Matches the reset flow. Two different minimums would mean a password that is
#: acceptable by one route and refused by the other.
MIN_LENGTH = 8


class ChangePassword:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, *, actor: User, current: str, new: str) -> None:
        if actor.hashed_password is None:
            # Invited but never claimed. There is no current password to check,
            # so the reset link is the only honest way in.
            raise ValidationError(
                "This account has no password yet. Use the link in your invitation."
            )

        if not verify_password(current, actor.hashed_password):
            raise AuthenticationError("That is not your current password.")

        if len(new) < MIN_LENGTH:
            raise ValidationError(
                f"A new password needs at least {MIN_LENGTH} characters."
            )
        if new == current:
            raise ValidationError("The new password is the same as the old one.")

        actor.hashed_password = hash_password(new)
        await self._users.set_password(actor)
