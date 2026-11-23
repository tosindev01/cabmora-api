from dataclasses import dataclass

from app.core.exceptions import AuthenticationError
from app.core.security import create_access_token, verify_password
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository


@dataclass
class LoginResult:
    user: User
    access_token: str
    token_type: str = "bearer"


class LoginUser:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, email: str, password: str) -> LoginResult:
        user = await self._users.get_by_email(email.lower())
        # An account created by an admin has no password until the invite is
        # accepted. Refused with the same message as a wrong password so the
        # endpoint does not reveal which accounts exist but are unclaimed.
        if user is None or user.hashed_password is None:
            raise AuthenticationError("Invalid email or password")
        if not verify_password(password, user.hashed_password):
            raise AuthenticationError("Invalid email or password")
        # Pending accounts sign in on purpose — they must reach the screen that
        # explains they are awaiting acceptance. Only suspension blocks login.
        if not user.can_authenticate:
            raise AuthenticationError("Account is suspended")

        token = create_access_token(str(user.id), {"role": user.role.value})
        return LoginResult(user=user, access_token=token)
