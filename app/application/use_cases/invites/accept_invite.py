from app.core.exceptions import AuthenticationError
from app.core.security import hash_password
from app.domain.entities.invite import InviteToken
from app.domain.entities.user import User
from app.domain.repositories.invite_repository import InviteRepository
from app.domain.repositories.user_repository import UserRepository


class AcceptInvite:
    """Claim an account created by an admin, by setting a password."""

    def __init__(self, users: UserRepository, invites: InviteRepository) -> None:
        self._users = users
        self._invites = invites

    async def execute(self, token: str, password: str) -> User:
        invite = await self._invites.get_by_hash(InviteToken.hash_of(token))

        # One message for unknown, expired and already-used. Distinguishing
        # them tells someone holding a guessed token which guesses are close,
        # and tells anyone whether an invite exists for an address.
        if invite is None or not invite.is_usable():
            raise AuthenticationError("This invite link is invalid or has expired.")

        user = await self._users.get_by_id(invite.user_id)
        if user is None:
            raise AuthenticationError("This invite link is invalid or has expired.")

        user.hashed_password = hash_password(password)
        updated = await self._users.set_password(user)
        # Marked used only after the password is stored: failing the other way
        # round would burn the invite and leave the account unclaimable.
        await self._invites.mark_used(invite)
        return updated
