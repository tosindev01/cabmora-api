"""Spend a reset link and set a new password."""

from app.core.exceptions import AuthenticationError
from app.core.security import hash_password
from app.domain.entities.password_reset import PasswordResetToken
from app.domain.entities.user import User, UserStatus
from app.domain.repositories.password_reset_repository import PasswordResetRepository
from app.domain.repositories.user_repository import UserRepository

#: One message for every way this can fail.
_REFUSAL = "This reset link is invalid or has expired."


class ResetPassword:
    def __init__(
        self, users: UserRepository, tokens: PasswordResetRepository
    ) -> None:
        self._users = users
        self._tokens = tokens

    async def execute(self, token: str, password: str) -> User:
        record = await self._tokens.get_by_hash(PasswordResetToken.hash_of(token))

        # Unknown, expired and already-spent all say the same thing.
        # Distinguishing them tells someone holding a guessed token which
        # guesses are close, and tells anyone whether an address has an
        # account at all.
        if record is None or not record.is_usable():
            raise AuthenticationError(_REFUSAL)

        user = await self._users.get_by_id(record.user_id)
        if user is None or user.status is UserStatus.SUSPENDED:
            raise AuthenticationError(_REFUSAL)

        user.hashed_password = hash_password(password)
        updated = await self._users.set_password(user)
        # Marked used only after the password is stored. Failing the other way
        # round would spend the link and leave the account unreachable.
        await self._tokens.mark_used(record)
        return updated
